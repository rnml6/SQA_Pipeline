"""TRN-003: standardize types, dates, timestamps, and approved reference values.

Rules implemented here (Section 4):
    S-01  schedules.date                 -> ISO 8601 YYYY-MM-DD (reject on failure)
    S-02  conditions.created_at          -> ISO 8601 timestamp (reject on failure)
    S-03  text fields                    -> trimmed, consistent text format
    S-04  identifiers                    -> applied by TRN-002 before relationships
    S-05  risk_level                     -> approved CitiCare mapping (quarantine others)
    S-06  schedules.status               -> approved schedule-status mapping
    S-07  condition_name                 -> approved naming convention

No new clinical category, risk level, or schedule status is created here.
"""

from __future__ import annotations

from collections import Counter

from trn000_config import (
    RISK_LEVEL_MAP,
    SCHEDULE_STATUS_MAP,
    DATASETS,
    PROCESSING_ORDER,
    iso_timestamp,
    normalize_space,
    parse_iso_date,
    parse_iso_timestamp,
    quarantine_row,
    title_case,
)


def _reject(context: dict, dataset: str, row: dict, quarantine: list[dict],
            rules: Counter, rejected: Counter, rule_id: str, column: str,
            code: str, reason: str) -> None:
    pk_column = DATASETS[dataset]["primary_key"]
    quarantine.append(
        quarantine_row(context, dataset, row.get(pk_column), rule_id, column,
                       row.get(column), code, reason)
    )
    rejected[dataset] += 1
    rules[rule_id] += 1


def _standardize_puroks(rows, context, quarantine, rules, rejected):
    output = []
    for row in rows:
        name = title_case(row["name"])
        if name != row["name"]:
            rules["S-03"] += 1
        output.append({
            "purok_id": row["purok_id"],
            "name": name,
            "_modified": row.get("_modified", False) or name != row["name"],
        })
    return output


def _standardize_residents(rows, context, quarantine, rules, rejected):
    output = []
    for row in rows:
        raw = normalize_space(row["risk_level"])
        risk_level = RISK_LEVEL_MAP.get(raw.upper())
        if risk_level is None:
            _reject(context, "residents", row, quarantine, rules, rejected, "S-05",
                    "risk_level", "UNRECOGNIZED_RISK_LEVEL",
                    "risk_level is not covered by the approved CitiCare mapping")
            continue
        if risk_level != raw:
            rules["S-05"] += 1
        output.append({
            "resident_id": row["resident_id"],
            "purok_id": row["purok_id"],
            "risk_level": risk_level,
            "_modified": row.get("_modified", False) or risk_level != raw,
        })
    return output


def _standardize_conditions(rows, context, quarantine, rules, rejected):
    output = []
    for row in rows:
        recorded_at = parse_iso_timestamp(row["created_at"])
        if recorded_at is None:
            _reject(context, "resident_chronic_conditions", row, quarantine, rules, rejected,
                    "S-02", "created_at", "INVALID_TIMESTAMP",
                    "created_at is not a valid ISO 8601 timestamp")
            continue

        name = title_case(row["condition_name"])
        if name != row["condition_name"]:
            rules["S-07"] += 1
        created_at = iso_timestamp(recorded_at)
        output.append({
            "condition_id": row["condition_id"],
            "resident_id": row["resident_id"],
            "condition_name": name,
            "created_at": created_at,
            "_modified": (
                row.get("_modified", False)
                or name != row["condition_name"]
                or created_at != row["created_at"]
            ),
        })
    return output


def _standardize_schedules(rows, context, quarantine, rules, rejected):
    output = []
    for row in rows:
        schedule_date = parse_iso_date(row["date"])
        if schedule_date is None:
            _reject(context, "schedules", row, quarantine, rules, rejected, "S-01",
                    "date", "INVALID_DATE",
                    "date is not a valid ISO 8601 date (YYYY-MM-DD)")
            continue

        raw_status = normalize_space(row["status"])
        status = SCHEDULE_STATUS_MAP.get(raw_status.upper())
        if status is None:
            _reject(context, "schedules", row, quarantine, rules, rejected, "S-06",
                    "status", "UNRECOGNIZED_SCHEDULE_STATUS",
                    "status is not covered by the approved schedule-status mapping")
            continue
        if status != raw_status:
            rules["S-06"] += 1

        date_text = schedule_date.isoformat()
        output.append({
            "schedule_id": row["schedule_id"],
            "resident_id": row["resident_id"],
            "date": date_text,
            "status": status,
            "_modified": (
                row.get("_modified", False)
                or status != raw_status
                or date_text != row["date"]
            ),
        })
    return output


_STANDARDIZERS = {
    "puroks": _standardize_puroks,
    "residents": _standardize_residents,
    "resident_chronic_conditions": _standardize_conditions,
    "schedules": _standardize_schedules,
}


def standardize(records: dict[str, list[dict]], context: dict) -> dict:
    """Convert cleaned values to the contracted types and formats."""
    quarantine: list[dict] = []
    rules: Counter = Counter()
    rejected: Counter = Counter()
    output: dict[str, list[dict]] = {}

    for name in PROCESSING_ORDER:
        output[name] = _STANDARDIZERS[name](
            records[name], context, quarantine, rules, rejected
        )

    modified = Counter({
        name: sum(1 for row in rows if row.get("_modified"))
        for name, rows in output.items()
    })

    return {
        "records": output,
        "quarantine": quarantine,
        "rules": rules,
        "rejected": rejected,
        "modified": modified,
    }
