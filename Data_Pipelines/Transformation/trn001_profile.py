"""TRN-001: profile the Stage 1 handover before any cleaning rule runs.

Section 2 requires profiling before cleaning. Every documented potential issue
is measured against the received CSV files; the profile records counts, sample
values, and the rule planned to treat each finding.
"""

from __future__ import annotations

from collections import Counter

from trn000_config import (
    APPROVED_RISK_LEVELS,
    APPROVED_SCHEDULE_STATUSES,
    DATASETS,
    PROCESSING_ORDER,
    RISK_LEVEL_MAP,
    SCHEDULE_STATUS_MAP,
    iso_timestamp,
    key_token,
    normalize_space,
    parse_iso_date,
    parse_iso_timestamp,
    recover_condition_name,
    title_case,
    to_int,
    utc_now,
)


def _matches_domain(value: object, mapping: dict[str, str], approved: frozenset[str]) -> bool:
    text = normalize_space(value)
    return text.upper() in mapping and mapping[text.upper()] in approved


def _is_consistent_text(value: object) -> bool:
    text = normalize_space(value)
    return text == title_case(text)


def _issue(issue_id: str, dataset: str, column: str, issue_type: str, example: object,
           affected: int, total: int, treatment: str, **detail) -> dict:
    entry = {
        "id": issue_id,
        "file": DATASETS[dataset]["file"] if dataset in DATASETS else "all files",
        "dataset": dataset,
        "column": column,
        "issue_type": issue_type,
        "example": "" if example is None else str(example)[:120],
        "affected_records": affected,
        "percentage_of_file": round(100.0 * affected / total, 2) if total else 0.0,
        "planned_treatment": treatment,
    }
    if detail:
        entry["detail"] = detail
    return entry


def profile(records: dict[str, list[dict]], schema: dict[str, dict], context: dict) -> dict:
    """Return measured dataset summaries and the Section 2 issue register."""
    datasets: dict[str, dict] = {}
    for name in PROCESSING_ORDER:
        rows = records.get(name, [])
        spec = DATASETS[name]
        keys = [key_token(row.get(spec["primary_key"])) for row in rows]
        primary_key = spec["primary_key"]
        timestamps: dict[str, int] = {}
        for column in ("created_at", "updated_at"):
            if column in (rows[0].keys() if rows else []):
                timestamps[column] = sum(
                    1 for row in rows if parse_iso_timestamp(row.get(column)) is None
                )
        datasets[name] = {
            "file": spec["file"],
            "records": len(rows),
            "columns": schema.get(name, {}).get("columns", []),
            "required_columns": spec["required"],
            "optional_columns": schema.get(name, {}).get("optional_columns", []),
            "unexpected_columns": schema.get(name, {}).get("unexpected_columns", []),
            "blank_required_values": sum(
                1
                for row in rows
                for column in spec["required"]
                if normalize_space(row.get(column)) == ""
            ),
            "duplicate_primary_keys": len(keys) - len(set(keys)),
            "distinct_primary_keys": len(set(keys)),
            "invalid_primary_keys": sum(
                1
                for row in rows
                if normalize_space(row.get(primary_key)) != ""
                and to_int(row.get(primary_key)) is None
            ),
            "enumerations": {
                column: dict(Counter(normalize_space(row.get(column)) for row in rows))
                for column in ("risk_level", "status")
                if rows and column in rows[0]
            },
            "whitespace_affected": sum(
                1
                for row in rows
                if any(
                    isinstance(value, str) and value != normalize_space(value)
                    for value in row.values()
                )
            ),
            "invalid_timestamps": timestamps,
        }

    issues = detect_issues(records)
    return {
        "batch_id": context["batch_id"],
        "run_id": context["run_id"],
        "parent_run_id": context["parent_run_id"],
        "profiled_at": iso_timestamp(utc_now()),
        "records_profiled": sum(len(rows) for rows in records.values()),
        "datasets": datasets,
        "issues": issues,
    }


def detect_issues(records: dict[str, list[dict]]) -> list[dict]:
    """Measure every issue named in the Section 2 profiling table."""
    issues: list[dict] = []
    puroks = records.get("puroks", [])
    residents = records.get("residents", [])
    conditions = records.get("resident_chronic_conditions", [])
    schedules = records.get("schedules", [])

    purok_ids = {key_token(row.get("purok_id")) for row in puroks}
    resident_ids = {key_token(row.get("resident_id")) for row in residents}

    # --- puroks -----------------------------------------------------------
    purok_pk = [key_token(row.get("purok_id")) for row in puroks]
    purok_duplicates = len(purok_pk) - len(set(purok_pk))
    purok_blank = sum(1 for row in puroks if normalize_space(row.get("purok_id")) == "")
    issues.append(_issue(
        "P-01", "puroks", "purok_id", "Missing or duplicate identifier",
        next((row.get("purok_id") for row in puroks
              if normalize_space(row.get("purok_id")) == ""), "duplicate key"),
        purok_blank + purok_duplicates, len(puroks),
        "Reject blank identifiers (C-01); quarantine duplicate keys (C-03)",
        blank=purok_blank, duplicates=purok_duplicates,
    ))

    name_whitespace = sum(
        1 for row in puroks if normalize_space(row.get("name")) != row.get("name")
    )
    name_blank = sum(1 for row in puroks if normalize_space(row.get("name")) == "")
    issues.append(_issue(
        "P-02", "puroks", "name", "Leading/trailing whitespace or missing value",
        next((row.get("name") for row in puroks
              if normalize_space(row.get("name")) != row.get("name")), "blank name"),
        name_whitespace + name_blank, len(puroks),
        "Trim whitespace (C-02); reject missing name (C-01)",
        whitespace=name_whitespace, blank=name_blank,
    ))

    invalid_purok_names = [
        row for row in puroks
        if normalize_space(row.get("name")) and not any(
            character.isalpha() for character in normalize_space(row.get("name"))
        )
    ]
    issues.append(_issue(
        "P-03", "puroks", "name", "Invalid characters (no alphabetic content)",
        invalid_purok_names[0].get("name") if invalid_purok_names else "", len(invalid_purok_names),
        len(puroks), "Quarantine the record (C-06)",
    ))

    # --- residents --------------------------------------------------------
    resident_pk = [key_token(row.get("resident_id")) for row in residents]
    resident_duplicates = len(resident_pk) - len(set(resident_pk))
    resident_blank = sum(1 for row in residents if normalize_space(row.get("resident_id")) == "")
    issues.append(_issue(
        "P-04", "residents", "resident_id", "Missing or duplicate identifier",
        next((row.get("resident_id") for row in residents
              if normalize_space(row.get("resident_id")) == ""), "duplicate key"),
        resident_blank + resident_duplicates, len(residents),
        "Reject blank identifiers (C-01); quarantine duplicate keys (C-03)",
        blank=resident_blank, duplicates=resident_duplicates,
    ))

    purok_missing = sum(
        1 for row in residents if normalize_space(row.get("purok_id")) == ""
    )
    purok_orphans = sum(
        1 for row in residents
        if normalize_space(row.get("purok_id"))
        and key_token(row.get("purok_id")) not in purok_ids
    )
    issues.append(_issue(
        "P-05", "residents", "purok_id", "Missing or unmatched reference",
        next((row.get("purok_id") for row in residents
              if key_token(row.get("purok_id")) not in purok_ids), "missing parent"),
        purok_missing + purok_orphans, len(residents),
        "Reject missing value (C-01); quarantine orphan reference (C-05)",
        missing=purok_missing, unmatched=purok_orphans,
    ))

    risk_affected = [
        row for row in residents
        if normalize_space(row.get("risk_level")) == ""
        or not _matches_domain(row.get("risk_level"), RISK_LEVEL_MAP, APPROVED_RISK_LEVELS)
        or normalize_space(row.get("risk_level")) != RISK_LEVEL_MAP.get(
            normalize_space(row.get("risk_level")).upper()
        )
    ]
    issues.append(_issue(
        "P-06", "residents", "risk_level", "Inconsistent text or unrecognized value",
        next((row.get("risk_level") for row in risk_affected), ""), len(risk_affected),
        len(residents), "Clean text and apply the approved mapping (C-02, S-03, S-05)",
    ))

    # --- resident_chronic_conditions -------------------------------------
    condition_pk = [key_token(row.get("condition_id")) for row in conditions]
    condition_duplicates = len(condition_pk) - len(set(condition_pk))
    condition_blank = sum(
        1 for row in conditions if normalize_space(row.get("condition_id")) == ""
    )
    issues.append(_issue(
        "P-07", "resident_chronic_conditions", "condition_id",
        "Missing or duplicate identifier",
        next((row.get("condition_id") for row in conditions
              if normalize_space(row.get("condition_id")) == ""), "duplicate key"),
        condition_blank + condition_duplicates, len(conditions),
        "Reject blank identifiers (C-01); quarantine duplicate keys (C-03)",
        blank=condition_blank, duplicates=condition_duplicates,
    ))

    condition_orphans = sum(
        1 for row in conditions
        if normalize_space(row.get("resident_id"))
        and key_token(row.get("resident_id")) not in resident_ids
    )
    issues.append(_issue(
        "P-08", "resident_chronic_conditions", "resident_id", "Orphan relationship",
        next((row.get("resident_id") for row in conditions
              if key_token(row.get("resident_id")) not in resident_ids), ""),
        condition_orphans, len(conditions), "Quarantine the record (C-05)",
    ))

    embedded = [
        row for row in conditions
        if normalize_space(row.get("condition_name")).startswith("{")
    ]
    issues.append(_issue(
        "P-09", "resident_chronic_conditions", "condition_name",
        "Embedded document instead of a condition name",
        embedded[0].get("condition_name") if embedded else "", len(embedded),
        len(conditions),
        "Correct to the documented name member (C-06, S-07) or quarantine (C-04)",
    ))

    name_format = []
    for row in conditions:
        recovered, _ = recover_condition_name(row.get("condition_name"))
        if not recovered:
            continue
        raw = normalize_space(row.get("condition_name"))
        if recovered != raw or not _is_consistent_text(recovered):
            name_format.append(row)
    issues.append(_issue(
        "P-10", "resident_chronic_conditions", "condition_name",
        "Whitespace or inconsistent casing",
        name_format[0].get("condition_name") if name_format else "",
        len(name_format), len(conditions),
        "Trim and apply the approved naming convention (C-02, S-07)",
    ))

    invalid_timestamps = [
        row for row in conditions
        if parse_iso_timestamp(row.get("created_at")) is None
    ]
    issues.append(_issue(
        "P-11", "resident_chronic_conditions", "created_at", "Invalid timestamp format",
        invalid_timestamps[0].get("created_at") if invalid_timestamps else "",
        len(invalid_timestamps), len(conditions),
        "Convert to ISO 8601 or quarantine (S-02)",
    ))

    # --- schedules --------------------------------------------------------
    schedule_pk = [key_token(row.get("schedule_id")) for row in schedules]
    schedule_duplicates = len(schedule_pk) - len(set(schedule_pk))
    schedule_blank = sum(
        1 for row in schedules if normalize_space(row.get("schedule_id")) == ""
    )
    issues.append(_issue(
        "P-12", "schedules", "schedule_id", "Missing or duplicate identifier",
        next((row.get("schedule_id") for row in schedules
              if normalize_space(row.get("schedule_id")) == ""), "duplicate key"),
        schedule_blank + schedule_duplicates, len(schedules),
        "Reject blank identifiers (C-01); quarantine duplicate keys (C-03)",
        blank=schedule_blank, duplicates=schedule_duplicates,
    ))

    schedule_orphans = sum(
        1 for row in schedules
        if normalize_space(row.get("resident_id"))
        and key_token(row.get("resident_id")) not in resident_ids
    )
    issues.append(_issue(
        "P-13", "schedules", "resident_id", "Orphan relationship",
        next((row.get("resident_id") for row in schedules
              if key_token(row.get("resident_id")) not in resident_ids), ""),
        schedule_orphans, len(schedules), "Quarantine the record (C-05)",
    ))

    invalid_dates = [row for row in schedules if parse_iso_date(row.get("date")) is None]
    issues.append(_issue(
        "P-14", "schedules", "date", "Invalid or inconsistent date",
        invalid_dates[0].get("date") if invalid_dates else "", len(invalid_dates),
        len(schedules), "Convert to ISO 8601 date or quarantine (S-01)",
    ))

    status_affected = [
        row for row in schedules
        if normalize_space(row.get("status")) == ""
        or not _matches_domain(
            row.get("status"), SCHEDULE_STATUS_MAP, APPROVED_SCHEDULE_STATUSES
        )
        or normalize_space(row.get("status")) != SCHEDULE_STATUS_MAP.get(
            normalize_space(row.get("status")).upper()
        )
    ]
    issues.append(_issue(
        "P-15", "schedules", "status", "Inconsistent or unrecognized value",
        next((row.get("status") for row in status_affected), ""), len(status_affected),
        len(schedules), "Clean text and apply the approved mapping (C-02, S-03, S-06)",
    ))

    # --- all files --------------------------------------------------------
    whitespace = sum(
        1
        for name in PROCESSING_ORDER
        for row in records.get(name, [])
        if any(
            isinstance(value, str) and value != normalize_space(value)
            for value in row.values()
        )
    )
    issues.append(_issue(
        "P-16", "all", "all text columns", "Leading/trailing or repeated whitespace",
        "measured across all four files", whitespace,
        sum(len(records.get(name, [])) for name in PROCESSING_ORDER),
        "Trim and collapse whitespace (C-02)",
    ))

    return issues
