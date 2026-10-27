"""TRN-000: shared paths, contracts, approved mappings, versions, and helpers.

Everything in this module implements the controlled vocabulary of the
CitiCare Stage 2 Data Transformation Documentation:

* Section 1.1  input source and required metadata
* Section 1.3  transformation scope (fields in scope per file)
* Section 3    cleaning rules C-01 to C-06
* Section 4    standardization rules S-01 to S-07 and approved reference values
* Section 5    business rules B-01 to B-05
* Section 6    transformed data contract (output files and columns)
* Section 8.1  metadata fields and version identifiers
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

STAGE_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = STAGE_DIR.parent / "Extraction"
DEFAULT_INPUT_DIR = EXTRACTION_DIR / "data" / "handover"
LEGACY_INPUT_DIR = EXTRACTION_DIR / "data" / "input"
HANDOVER_CHECKPOINT = EXTRACTION_DIR / "data" / "checkpoint.json"

OUTPUT_DIR = STAGE_DIR / "output"
LOG_DIR = STAGE_DIR / "logs"
PROFILE_DIR = LOG_DIR / "profile"
AUDIT_DIR = LOG_DIR / "audit"
CHECKPOINT_DIR = LOG_DIR / "checkpoints"
QUARANTINE_DIR = STAGE_DIR / "quarantine"


def default_input_dir() -> Path:
    """Prefer the approved Stage 1 handover; fall back to legacy staging."""
    if (DEFAULT_INPUT_DIR / "handover.json").is_file():
        return DEFAULT_INPUT_DIR
    return LEGACY_INPUT_DIR


# Section 8.1: code and rule set versions.
CODE_VERSION = "TRN-2.1.0"
RULES_VERSION = "RULES-2.0.0"

# Section 1.4: required processing order. Parents are cleaned before children so
# orphan-relationship checks run against the approved parent reference set.
PROCESSING_ORDER = ["puroks", "residents", "resident_chronic_conditions", "schedules"]

# Section 1.1 / 1.3 and the Stage 1 extraction contract (Section 6.1).
#
# ``optional`` columns are sourced by Stage 1 when the source system exposes
# them (see ``TIMESTAMP_COLUMNS`` in ext001_extract.py). They are part of the
# received staging schema but are not part of the Stage 2 output contract, so
# they are recorded as not carried forward instead of being treated as an
# unexpected schema change. A column that is neither required nor optional is
# reported as an unexpected column (Section 6.4).
DATASETS = {
    "puroks": {
        "file": "puroks.csv",
        "primary_key": "purok_id",
        "required": ["purok_id", "name"],
        "optional": ["created_at", "updated_at"],
        "text_fields": ["name"],
        "output": [("purok_id", "integer"), ("name", "text")],
    },
    "residents": {
        "file": "residents.csv",
        "primary_key": "resident_id",
        "required": ["resident_id", "purok_id", "risk_level"],
        "optional": ["created_at", "updated_at"],
        "text_fields": ["risk_level"],
        "foreign_keys": {"purok_id": "puroks"},
        "output": [("resident_id", "integer"), ("purok_id", "integer"), ("risk_level", "text")],
    },
    "resident_chronic_conditions": {
        "file": "resident_chronic_conditions.csv",
        "primary_key": "condition_id",
        "required": ["condition_id", "resident_id", "condition_name", "created_at"],
        "optional": ["updated_at"],
        "text_fields": ["condition_name"],
        "foreign_keys": {"resident_id": "residents"},
        "output": [
            ("condition_id", "integer"),
            ("resident_id", "integer"),
            ("condition_name", "text"),
            ("created_at", "timestamp"),
        ],
    },
    "schedules": {
        "file": "schedules.csv",
        "primary_key": "schedule_id",
        "required": ["schedule_id", "resident_id", "date", "status"],
        "optional": ["updated_at", "created_at"],
        "text_fields": ["status"],
        "foreign_keys": {"resident_id": "residents"},
        "output": [
            ("schedule_id", "integer"),
            ("resident_id", "integer"),
            ("date", "date"),
            ("status", "text"),
        ],
    },
}

# Section 6.1: the only approved output datasets. The output keeps the
# documented identifiers and fields; no surrogate keys, dimensional prefixes,
# or derived summary tables are defined by the approved contract.
OUTPUT_FILES = {
    name: {
        "file": spec["file"],
        "columns": [column for column, _ in spec["output"]],
        "types": dict(spec["output"]),
    }
    for name, spec in DATASETS.items()
}

# Section 4.2 S-05: approved CitiCare risk-level mapping. Recognized source
# spellings are mapped to the approved code. No new risk category may be
# invented; anything not listed here is quarantined for review.
RISK_LEVEL_MAP = {
    "LOW": "LOW",
    "LOW RISK": "LOW",
    "MODERATE": "MODERATE",
    "MODERATE RISK": "MODERATE",
    "HIGH": "HIGH",
    "HIGH RISK": "HIGH",
    "CRITICAL": "CRITICAL",
    "CRITICAL RISK": "CRITICAL",
}
APPROVED_RISK_LEVELS = frozenset(RISK_LEVEL_MAP.values())

# Section 4.2 S-06: approved schedule-status mapping. ``CANCELLED`` remains a
# valid documented status; no business exclusion of it is defined by the
# approved output contract.
SCHEDULE_STATUS_MAP = {
    "COMPLETED": "COMPLETED",
    "COMPLETE": "COMPLETED",
    "DONE": "COMPLETED",
    "MISSED": "MISSED",
    "NO SHOW": "MISSED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
}
APPROVED_SCHEDULE_STATUSES = frozenset(SCHEDULE_STATUS_MAP.values())

# Section 4 S-03/S-07: approved consistent text format (title case applied to
# purok names and condition names after whitespace cleanup). The meaning of the
# value is preserved; only presentation is standardized.
TEXT_FORMAT = "TITLE_CASE"

# Section 4 S-07/C-06: an embedded JSON document is not a valid condition name.
# The approved correction keeps the documented ``name`` member and discards the
# other members, because no severity column exists in the approved output
# contract. If no usable name remains the record is quarantined under C-04.
EMBEDDED_DOCUMENT_SEPARATOR = "{"

# Section 10.1: the rejection-rate threshold must be formally approved by the
# project before production. The value is configuration, not a rule invented by
# this code; override it with CITICARE_TRN_REJECTION_RATE_LIMIT once the
# project-approved threshold is issued.
REJECTION_RATE_LIMIT = float(os.getenv("CITICARE_TRN_REJECTION_RATE_LIMIT", "0.05"))

# Section 9.1: minimum content retained for every rejected record.
QUARANTINE_COLUMNS = [
    "batch_id",
    "run_id",
    "parent_run_id",
    "source_file",
    "source_table",
    "source_pk",
    "rule_id",
    "column_name",
    "raw_value",
    "reason_code",
    "reason",
    "quarantined_at",
]

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
)


class HandoverError(Exception):
    """A controlled pipeline failure with an approved error code (Section 8.1)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime | None) -> str | None:
    """Return an ISO 8601 UTC timestamp, preserving microseconds (S-02)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}"
    return text + "Z"


def normalize_space(value: object) -> str:
    """Trim and collapse whitespace, drop control and zero-width characters."""
    text = str(value if value is not None else "")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())


def title_case(value: object) -> str:
    """Apply the approved consistent text format without changing meaning."""
    return " ".join(part.capitalize() for part in normalize_space(value).split())


def key_token(value: object) -> str:
    """Canonical comparison token for identifier matching.

    Integers compare numerically (``"01"`` matches ``"1"``); anything that is
    not integer-compatible is compared as trimmed text and later rejected by
    the S-04 conversion rule.
    """
    text = normalize_space(value)
    try:
        return str(int(text))
    except ValueError:
        return text


def recover_condition_name(value: object) -> tuple[str, bool]:
    """Return ``(name, was_embedded_document)`` for a condition_name value.

    Section 4 S-07 / C-06: an embedded JSON document is not a valid condition
    name. The approved correction keeps the documented ``name`` member and
    discards members that have no column in the approved output contract. An
    unreadable or unusable document returns an empty name so the record can be
    quarantined under C-04.
    """
    text = normalize_space(value)
    if not text.startswith(EMBEDDED_DOCUMENT_SEPARATOR):
        return text, False
    try:
        payload = json.loads(text)
    except ValueError:
        return "", True
    if not isinstance(payload, dict):
        return "", True
    return normalize_space(payload.get("name", "")), True


def to_int(value: object) -> int | None:
    """S-04: convert an identifier to an integer-compatible value."""
    text = normalize_space(value)
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def approved_reference_keys(reference: dict, dataset: str) -> set[int]:
    """Return reference parent keys that pass the applicable approved rules.

    The reference retains previously approved parents for incremental batches.
    A purok with no usable alphabetic name is not a valid parent (C-06), so it
    must not make a child appear referentially valid.
    """
    key = DATASETS[dataset]["primary_key"]
    keys = set()
    for row in (reference or {}).get(dataset, []):
        value = to_int(row.get(key))
        if value is None:
            continue
        if dataset == "puroks":
            name = normalize_space(row.get("name"))
            if not name or not any(character.isalpha() for character in name):
                continue
        keys.add(value)
    return keys


def parse_iso_date(value: object) -> date | None:
    """S-01: parse only the unambiguous ISO 8601 date form."""
    text = normalize_space(value)
    if not ISO_DATE_PATTERN.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_iso_timestamp(value: object) -> datetime | None:
    """S-02: parse an ISO 8601 timestamp without ambiguous locale assumptions."""
    text = normalize_space(value)
    if text == "":
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # The CitiCare source contract stores UTC; a naive value is therefore
        # interpreted as UTC rather than under the host locale.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def previous_month(value: date) -> date:
    year, month = value.year, value.month - 1
    if month == 0:
        year, month = year - 1, 12
    return date(year, month, min(value.day, 28))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def quarantine_row(context: dict, dataset: str, source_pk: object, rule_id: str,
                   column: str, raw: object, code: str, reason: str) -> dict:
    """Build one Section 9.1 quarantine record (minimum necessary content)."""
    spec = DATASETS[dataset]
    return {
        "batch_id": context["batch_id"],
        "run_id": context["run_id"],
        "parent_run_id": context["parent_run_id"],
        "source_file": spec["file"],
        "source_table": dataset,
        "source_pk": "" if source_pk is None else str(source_pk),
        "rule_id": rule_id,
        "column_name": column,
        "raw_value": str(raw if raw is not None else "")[:200],
        "reason_code": code,
        "reason": reason,
        "quarantined_at": iso_timestamp(utc_now()),
    }


def append_event(path: Path, level: str, run_id: str, process: str, event: str,
                 fields: dict, timestamp: str | None = None) -> None:
    """Append one structured event to a line-oriented audit log (Section 8.2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or iso_timestamp(utc_now())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{timestamp} [{level}] citicare.transformation "
            f"process={process} run_id={run_id} event={event}\n"
        )
        for key, value in fields.items():
            text = "" if value is None else str(value).replace("\n", " ")
            handle.write(f'  {key}: "{text}"\n')
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv_dataset(path: Path, name: str) -> tuple[list[str], list[dict]]:
    """Read one handover CSV and enforce the received schema contract."""
    spec = DATASETS[name]
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            rows = [
                {str(key): ("" if value is None else value) for key, value in row.items()}
                for row in reader
            ]
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        raise HandoverError("CSV_READ_ERROR", f"{spec['file']}: {exc}") from exc

    missing_columns = [column for column in spec["required"] if column not in columns]
    if missing_columns:
        raise HandoverError(
            "SCHEMA_MISSING_COLUMN",
            f"{spec['file']}: missing required column(s) {missing_columns}",
        )
    return columns, rows


def read_handover(input_dir: Path) -> dict:
    """Read the approved Stage 1 handover without modifying it.

    Section 1.1 requires the extraction run ID, batch window, and acceptance
    status from the handover. Section 6.4 stops the batch on a missing required
    column and reports unexpected columns for review instead of silently
    including them.
    """
    input_dir = Path(input_dir)
    metadata = None
    handover_file = input_dir / "handover.json"
    if handover_file.is_file():
        try:
            metadata = json.loads(handover_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HandoverError(
                "HANDOVER_METADATA_INVALID", f"{handover_file}: {exc}"
            ) from exc
        status = metadata.get("handover_status") or metadata.get("extraction_status")
        if status != "APPROVED":
            raise HandoverError(
                "HANDOVER_NOT_APPROVED",
                f"Extraction handover status is {status or 'UNKNOWN'}; only "
                "APPROVED data may be transformed.",
            )

    missing = [
        str(input_dir / spec["file"])
        for spec in DATASETS.values()
        if not (input_dir / spec["file"]).is_file()
    ]
    if missing:
        raise HandoverError(
            "INPUT_FILES_MISSING",
            "Missing approved handover files: " + ", ".join(missing),
        )

    records: dict[str, list[dict]] = {}
    schema: dict[str, dict] = {}

    for name in PROCESSING_ORDER:
        spec = DATASETS[name]
        columns, rows = _read_csv_dataset(input_dir / spec["file"], name)
        records[name] = rows

        known = set(spec["required"]) | set(spec["optional"])
        schema[name] = {
            "columns": columns,
            "required_columns": spec["required"],
            "optional_columns": [column for column in spec["optional"] if column in columns],
            "unexpected_columns": [column for column in columns if column not in known],
            "not_carried_forward": [
                column for column in spec["optional"] if column in columns
                and column not in OUTPUT_FILES[name]["columns"]
            ],
        }

    # Section 5: validate children against the approved parent reference when
    # an incremental handover does not contain every referenced parent.
    reference: dict[str, list[dict]] = {}
    reference_dir = input_dir / "reference"
    for name in ("puroks", "residents"):
        path = reference_dir / DATASETS[name]["file"]
        if path.is_file():
            _, reference[name] = _read_csv_dataset(path, name)

    # Legacy staging or a full handover is its own parent reference.
    for name in ("puroks", "residents"):
        reference.setdefault(name, records[name])

    return {
        "records": records,
        "schema": schema,
        "reference": reference,
        "metadata": metadata,
    }
