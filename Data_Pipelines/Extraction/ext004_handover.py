"""EXT-004: acceptance decision, extraction metadata, logs, and handover."""

import csv
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ext001_extract import DATASETS

HANDOVER_DATASETS = [
    "puroks",
    "residents",
    "resident_chronic_conditions",
    "schedules",
]
REFERENCE_DATASETS = ["puroks", "residents"]
LOG_FILES = ("extract.log", "incremental.log", "validate.log", "handover.log")
LOG_RETENTION_DAYS = 365


def _month_key(moment):
    return f"{moment:%Y-%m}"


def archive_and_purge_logs(log_dir, now=None, retention_days=LOG_RETENTION_DAYS):
    """Archive the previous month's logs and purge archives past retention.

    Active logs hold only the current operational month. When a run starts in a
    new month, the previous month's log files are moved to
    ``logs/archive/<year>/<name>-<year>-<month>.log``. Archived operational logs
    older than ``retention_days`` are deleted. Audit records are not touched.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    current_month = _month_key(now)

    marker = log_dir / ".active_month"
    previous_month = (
        marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    )
    if not previous_month:
        active = [
            path for path in (log_dir / name for name in LOG_FILES)
            if path.is_file() and path.stat().st_size
        ]
        if active:
            newest = max(path.stat().st_mtime for path in active)
            previous_month = _month_key(datetime.fromtimestamp(newest, timezone.utc))

    archived = []
    if previous_month and previous_month != current_month:
        archive_dir = log_dir / "archive" / previous_month[:4]
        archive_dir.mkdir(parents=True, exist_ok=True)
        for name in LOG_FILES:
            source = log_dir / name
            if not source.is_file() or not source.stat().st_size:
                continue
            target = archive_dir / f"{source.stem}-{previous_month}.log"
            if target.exists():
                target = archive_dir / f"{source.stem}-{previous_month}-{now:%H%M%S}.log"
            shutil.move(str(source), str(target))
            archived.append(str(target))
    marker.write_text(current_month, encoding="utf-8")

    purged = []
    cutoff = now.timestamp() - retention_days * 86400
    archive_root = log_dir / "archive"
    hold = archive_root / ".hold"
    if archive_root.is_dir() and not hold.is_file():
        for path in sorted(archive_root.rglob("*.log")):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    purged.append(str(path))
            except OSError:
                continue
    return {
        "archived": archived,
        "purged": purged,
        "retention_days": retention_days,
        "held": hold.is_file(),
    }


def acceptance(validation, warnings):
    if validation.get("errors"):
        return "REJECTED"
    if warnings or validation.get("warnings"):
        return "MANUAL REVIEW"
    return "APPROVED"


def _handover_status(status):
    if status == "APPROVED":
        return "APPROVED"
    if status == "MANUAL REVIEW":
        return "HELD"
    return "REJECTED"


def _source_columns(input_dir, dataset):
    """Return the source CSV header so an empty handover still has a schema."""
    if input_dir is None:
        return list(DATASETS[dataset][1])
    path = Path(input_dir) / f"{dataset}.csv"
    if not path.is_file():
        return list(DATASETS[dataset][1])
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), list(DATASETS[dataset][1]))


def _write_rows(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _batch_window(extraction_window):
    """Format the approved handover window for the Stage 2 batch metadata."""
    current = extraction_window.get("current_extraction")
    previous = extraction_window.get("previous_successful_extraction")
    if extraction_window.get("full_load"):
        return f"FULL LOAD {str(current)[:10]}" if current else "FULL LOAD"
    if current and previous:
        return f"{str(previous)[:10]} to {str(current)[:10]}"
    if current:
        return str(current)[:10]
    return None


def write_handover(handover_dir, status, records, incremental, metadata, input_dir):
    """Write the validated handover atomically.

    APPROVED and MANUAL REVIEW runs publish CSV files; a manual-review run is
    marked ``HELD`` so Stage 2 refuses it until ``approve_handover`` records the
    authorized decision. REJECTED and FAILED runs invalidate the status marker
    while preserving any previous approved files for audit and recovery.
    """
    handover_dir = Path(handover_dir)
    publishable = status in ("APPROVED", "MANUAL REVIEW")
    records = records or {}
    incremental = incremental or {}
    handover_counts = {
        name: len(incremental.get(name, [])) if publishable else 0
        for name in HANDOVER_DATASETS
    }

    document = {
        "pipeline_run_id": metadata["pipeline_run_id"],
        "extraction_status": status,
        "handover_status": _handover_status(status),
        "extraction_start_timestamp": metadata["extraction_start_timestamp"],
        "extraction_end_timestamp": metadata["extraction_end_timestamp"],
        "extraction_window": metadata["extraction_window"],
        "batch_window": _batch_window(metadata["extraction_window"]),
        "records_read": metadata["records_read"],
        "records_extracted": handover_counts,
        "records_rejected": metadata["records_rejected"],
        "reference_counts": {},
        "files": metadata["files"],
        "error_message": metadata.get("error_message"),
    }

    if not publishable:
        handover_dir.mkdir(parents=True, exist_ok=True)
        document["preserved_previous_handover"] = any(
            (handover_dir / f"{name}.csv").is_file()
            for name in HANDOVER_DATASETS
        )
        temp_file = handover_dir / f".handover.{uuid4().hex}.tmp"
        temp_file.write_text(
            json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8"
        )
        os.replace(temp_file, handover_dir / "handover.json")
        return handover_dir

    temp = handover_dir.parent / f".{handover_dir.name}.tmp"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True, exist_ok=True)

    for dataset in HANDOVER_DATASETS:
        _write_rows(
            temp / f"{dataset}.csv",
            incremental.get(dataset, []),
            _source_columns(input_dir, dataset),
        )

    # Section 5: an incremental handover may not contain every parent, so
    # publish the validated parent reference alongside the batch.
    for dataset in REFERENCE_DATASETS:
        _write_rows(
            temp / "reference" / f"{dataset}.csv",
            records.get(dataset, []),
            _source_columns(input_dir, dataset),
        )
        document["reference_counts"][dataset] = len(records.get(dataset, []))

    (temp / "handover.json").write_text(
        json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8"
    )

    if handover_dir.exists():
        shutil.rmtree(handover_dir)
    temp.rename(handover_dir)
    return handover_dir


def _append_process_logs(log_dir, metadata, log_maintenance=None):
    """Append standard line-oriented records to each process .log file."""
    log_maintenance = log_maintenance or {
        "archived": [],
        "purged": [],
        "retention_days": LOG_RETENTION_DAYS,
        "held": False,
    }
    status = metadata["extraction_status"]
    level = "INFO" if status == "APPROVED" else "WARNING" if status == "MANUAL REVIEW" else "ERROR"
    timestamp = metadata["extraction_end_timestamp"]
    validation = metadata["validation_results"]

    def scalar(value):
        text = str(value if value not in (None, "") else "NULL")
        return '"' + text.replace('"', '\\"').replace("\n", " ") + '"'

    def write_event(path, process, event, fields):
        flattened = {}

        def flatten(name, value):
            if isinstance(value, dict):
                for child_name, child_value in value.items():
                    flatten(f"{name}_{child_name}", child_value)
            elif isinstance(value, list):
                flattened[name] = ",".join(str(item) for item in value)
            else:
                flattened[name] = value

        for key, value in fields.items():
            flatten(key, value)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(
                f"{timestamp} [{level}] citicare.extraction "
                f"process={process} pipeline_run_id={metadata['pipeline_run_id']} event={event}\n"
            )
            for key, value in flattened.items():
                log_file.write(f"  {key}: {scalar(value)}\n")
            log_file.write("\n")

    common = {
        "extraction_start_timestamp": metadata["extraction_start_timestamp"],
        "extraction_end_timestamp": metadata["extraction_end_timestamp"],
        "extraction_status": status,
        "extraction_duration_seconds": metadata["extraction_duration_seconds"],
    }

    for filename in metadata["files"] or ["extraction_run"]:
        dataset = Path(filename).stem
        write_event(log_dir / "extract.log", "extract", "source_exported", {
            "table_file_name": filename,
            "pipeline_stage": "Stage 1: Data Extraction",
            "source_system": "CitiCare: Barangay Gumamela Healthcare Monitoring System",
            "source_database": "CitiCare PostgreSQL Database",
            "file_format": "CSV",
            "extraction_type": "Incremental Batch Extraction",
            "extraction_tool": "Python",
            "extraction_schedule": "Monthly",
            "records_read": metadata["records_read"].get(dataset, 0),
            "records_extracted": metadata["records_extracted"].get(dataset, 0),
            "records_rejected": metadata["records_rejected"].get(dataset, 0),
            "error_message_code": metadata["error_message"] or "NULL",
            **common,
        })

    write_event(log_dir / "incremental.log", "incremental", "window_filtered", {
        "table_file_names": ",".join(metadata["files"] or ["None"]),
        "previous_successful_extraction": metadata["extraction_window"].get("previous_successful_extraction"),
        "current_extraction": metadata["extraction_window"].get("current_extraction"),
        "full_load": metadata["extraction_window"].get("full_load", False),
        "records_read": metadata["records_read"],
        "records_extracted": metadata["records_extracted"],
        "records_rejected": metadata["records_rejected"],
        "error_message_code": metadata["error_message"] or "NULL",
        **common,
    })

    write_event(log_dir / "validate.log", "validate", "validation_completed", {
        "table_file_names": ",".join(metadata["files"] or ["None"]),
        "records_read": metadata["records_read"],
        "validation_status": validation.get("status"),
        "check_count": len(validation.get("checks", [])),
        "error_count": len(validation.get("errors", [])),
        "warning_count": len(validation.get("warnings", [])),
        "error_message_code": metadata["error_message"] or "NULL",
        **common,
    })
    for check in validation.get("checks", []):
        write_event(log_dir / "validate.log", "validate", "check", {
            "check_name": check.get("name"),
            "target": check.get("target"),
            "purpose": check.get("purpose"),
            "severity": check.get("severity"),
            "criteria": check.get("criteria"),
            "check_status": check.get("status"),
            "check_detail": check.get("detail"),
        })
    for error in validation.get("errors", []):
        write_event(log_dir / "validate.log", "validate", "error", {"message": error})
    for warning in validation.get("warnings", []):
        write_event(log_dir / "validate.log", "validate", "warning", {"message": warning})

    write_event(log_dir / "handover.log", "handover", "acceptance_decision", {
        "table_file_names": ",".join(metadata["files"] or ["None"]),
        "records_extracted": metadata["records_extracted"],
        "records_rejected": metadata["records_rejected"],
        "validation_status": validation.get("status"),
        "handover_status": metadata["handover_status"],
        "handover_directory": metadata.get("handover_directory"),
        "handover_decision": (
            "AUTOMATIC_HANDOVER"
            if metadata["handover_status"] == "APPROVED"
            else "HELD"
            if metadata["handover_status"] == "HELD"
            else "NOT_HANDED_OVER"
        ),
        "logs_archived": log_maintenance["archived"],
        "logs_purged": log_maintenance["purged"],
        "log_retention_days": log_maintenance["retention_days"],
        "log_retention_hold": log_maintenance["held"],
        "error_message_code": metadata["error_message"] or "NULL",
        **common,
    })


def write_result(handover_dir, status, records_read, records_extracted, validation,
                 started_at, extraction_window, error_message=None, records_rejected=None,
                 records=None, incremental=None, input_dir=None):
    """Create the approved handover and retain Stage 1 operational and audit logs."""
    ended_at = datetime.now(timezone.utc)
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    duration_seconds = round((ended_at - started).total_seconds(), 3)
    run_id = f"CITICARE_EXT_{ended_at:%Y%m%d}_{uuid4().hex[:8]}"
    extracted = records_extracted or {name: 0 for name in records_read}
    if records_rejected is None:
        records_rejected = {
            name: max(int(records_read.get(name, 0)) - int(extracted.get(name, 0)), 0)
            for name in records_read
        }
    metadata = {
        "pipeline_run_id": run_id,
        "files": [f"{name}.csv" for name in records_read],
        "extraction_start_timestamp": started_at,
        "extraction_end_timestamp": ended_at.isoformat(),
        "extraction_status": status,
        "handover_status": _handover_status(status),
        "records_read": records_read,
        "records_extracted": extracted,
        "records_rejected": records_rejected,
        "extraction_window": extraction_window,
        "validation_results": validation,
        "error_message": error_message,
        "extraction_duration_seconds": duration_seconds,
    }
    handover_path = write_handover(
        handover_dir, status, records or {}, incremental or {}, metadata, input_dir
    )
    metadata["handover_directory"] = str(handover_path)

    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_maintenance = archive_and_purge_logs(log_dir)
    _append_process_logs(log_dir, metadata, log_maintenance)
    return str(handover_path), run_id, metadata


def approve_handover(handover_dir, reviewer):
    """Record the authorized manual-review decision for a HELD handover.

    Section 7: a MANUAL REVIEW run is held until the System Administrator or
    Developer confirms the warning is acceptable. Approval changes the marker
    only; the published data is unchanged.
    """
    handover_dir = Path(handover_dir)
    path = handover_dir / "handover.json"
    if not path.is_file():
        raise FileNotFoundError(f"No handover metadata found at {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("handover_status") != "HELD"
            or document.get("extraction_status") != "MANUAL REVIEW"):
        raise ValueError(
            f"Handover status is {document.get('handover_status')}; only a HELD "
            "MANUAL REVIEW handover can be approved."
        )

    reviewed_at = datetime.now(timezone.utc).isoformat()
    document["extraction_status"] = "APPROVED"
    document["handover_status"] = "APPROVED"
    document["reviewed_by"] = reviewer
    document["reviewed_at"] = reviewed_at
    temp_file = handover_dir / f".handover.{uuid4().hex}.tmp"
    temp_file.write_text(
        json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8"
    )
    os.replace(temp_file, path)

    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "handover.log").open("a", encoding="utf-8") as handle:
        handle.write(
            f"{reviewed_at} [INFO] citicare.extraction process=handover "
            f"pipeline_run_id={document['pipeline_run_id']} event=manual_approval\n"
        )
        handle.write('  handover_status: "APPROVED"\n')
        handle.write(f'  reviewer: "{reviewer}"\n')
        handle.write(f'  handover_directory: "{handover_dir}"\n\n')
    return document
