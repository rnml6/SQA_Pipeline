"""EXT-003: validate source files, schema, types, keys, and relationships.

Every check carries the Section 3 fields: name, target, purpose, severity, and
measurable PASS/FAIL criteria. A critical failure blocks handover; a
non-critical failure is recorded as a WARNING and routes the run to manual
review. Source connectivity is checked by EXT-001 before export and passed in
so it is recorded with the same structure.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ext001_extract import DATASETS
from ext002_incremental import parse_timestamp

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
INTEGER_COLUMNS = {"resident_id", "purok_id", "condition_id", "schedule_id"}
NUMERIC_COLUMNS = {"temperature", "blood_sugar", "bmi"}
DATE_COLUMNS = {"date"}
TIMESTAMP_COLUMNS = {"created_at", "updated_at"}
OPTIONAL_COLUMNS = {}


def _blank(value):
    return value is None or str(value).strip() == ""


def _valid_type(column, value):
    if _blank(value):
        return True
    value = str(value).strip()
    if column in INTEGER_COLUMNS:
        try:
            int(value)
            return True
        except ValueError:
            return False
    if column in NUMERIC_COLUMNS:
        try:
            Decimal(value)
            return True
        except InvalidOperation:
            return False
    if column in DATE_COLUMNS:
        try:
            date.fromisoformat(value[:10])
            return True
        except ValueError:
            return False
    if column in TIMESTAMP_COLUMNS:
        return parse_timestamp(value) is not None
    return True


def _check(check_id, name, target, purpose, severity, criteria, passed, detail,
           warning=False):
    status = "PASS" if passed else ("WARNING" if warning else "FAIL")
    return {
        "id": check_id,
        "name": name,
        "target": target,
        "purpose": purpose,
        "severity": severity,
        "criteria": criteria,
        "status": status,
        "detail": detail,
    }


def validate(records, connectivity=None):
    errors = []
    warnings = []
    checks = []

    if connectivity:
        checks.append(connectivity)
        if connectivity["status"] != "PASS":
            errors.append(connectivity["detail"])

    def record(check):
        checks.append(check)
        if check["status"] == "FAIL":
            errors.append(check["detail"])
        elif check["status"] == "WARNING":
            warnings.append(check["detail"])

    for dataset, (primary_key, required) in DATASETS.items():
        rows = records.get(dataset)
        record(_check(
            f"dataset:{dataset}", "Required Datasets",
            f"{dataset} dataset", "Ensure every required dataset is loaded",
            "Critical", "4 of 4 datasets are loaded successfully",
            rows is not None, f"Dataset present: {dataset}",
        ))
        if rows is None:
            continue
        columns = set(rows[0]) if rows else set(required)
        record(_check(
            f"snake_case:columns:{dataset}", "Column Naming Convention",
            f"{dataset} column names", "Detect inconsistent or unexpected naming",
            "Non-critical",
            "100% of column names match ^[a-z][a-z0-9]*(_[a-z0-9]+)*$",
            all(SNAKE_CASE.fullmatch(column) for column in columns),
            f"{dataset} column names follow snake_case",
            warning=True,
        ))
        missing = set(required) - columns
        record(_check(
            f"columns:{dataset}", "Required Columns",
            f"{dataset} required columns", "Ensure every required field exists",
            "Critical", "0 missing required columns",
            not missing, f"{dataset} required columns present",
        ))
        extra = sorted(columns - set(required) - {"created_at", "updated_at"})
        record(_check(
            f"columns_extra:{dataset}", "Unexpected Columns",
            f"{dataset} column names", "Report unexpected schema changes",
            "Non-critical", "0 unexpected columns",
            not extra,
            f"{dataset} has no unexpected columns" if not extra
            else f"{dataset} has additional columns: {extra}",
            warning=True,
        ))

        keys = [row.get(primary_key) for row in rows]
        record(_check(
            f"primary_key:{dataset}", "Primary Key Uniqueness",
            f"{dataset}.{primary_key}", "Detect duplicate identifiers",
            "Critical", "0 blank and 0 duplicate primary-key values",
            all(not _blank(value) for value in keys) and len(keys) == len(set(keys)),
            f"{dataset}.{primary_key} values are present and unique",
        ))
        for column in required:
            blanks = sum(_blank(row.get(column)) for row in rows)
            if column in OPTIONAL_COLUMNS.get(dataset, set()):
                record(_check(
                    f"required_values:{dataset}.{column}", "Identifier Presence",
                    f"{dataset}.{column}", "Allow documented optional values",
                    "Critical", "0 blank required values",
                    True, f"{dataset}.{column} allows null values",
                ))
            else:
                record(_check(
                    f"required_values:{dataset}.{column}", "Identifier Presence",
                    f"{dataset}.{column}", "Prevent missing required values",
                    "Critical", "0 blank values",
                    blanks == 0, f"{dataset}.{column} has {blanks} blank values",
                ))
            invalid_types = sum(
                not _valid_type(column, row.get(column))
                for row in rows if not _blank(row.get(column))
            )
            record(_check(
                f"data_type:{dataset}.{column}", "Data Type Conformity",
                f"{dataset}.{column}", "Verify values match the documented data type",
                "Critical", "0 invalid type values",
                invalid_types == 0, f"{dataset}.{column} has {invalid_types} invalid values",
            ))

    resident_ids = {row.get("resident_id") for row in records.get("residents", [])}
    purok_ids = {row.get("purok_id") for row in records.get("puroks", [])}
    record(_check(
        "foreign_key:resident_id", "Foreign Key Availability",
        "resident_id relationship columns", "Verify relationships can be maintained",
        "Critical", "0 extracted resident_id values absent from residents",
        all(
            row.get("resident_id") in resident_ids
            for rows in records.values() for row in rows if "resident_id" in row
        ),
        "resident_id foreign keys are available",
    ))
    record(_check(
        "foreign_key:purok_id", "Foreign Key Availability",
        "residents.purok_id", "Verify relationships can be maintained",
        "Critical", "0 extracted purok_id values absent from puroks",
        all(row.get("purok_id") in purok_ids for row in records.get("residents", [])),
        "residents.purok_id foreign keys are available",
    ))
    return {"status": "FAIL" if errors else "PASS", "checks": checks,
            "errors": errors, "warnings": warnings}


def attach_reconciliation(validation, records_read, records_extracted):
    """Append the Section 3 Record Count Reconciliation check.

    ``records_extracted`` is the incremental handover count, so this verifies
    the documented ``extracted + rejected = read`` equation on the actual
    acceptance decision rather than trusting a derived total.
    """
    mismatches = []
    for name, read in records_read.items():
        extracted = int(records_extracted.get(name, 0))
        rejected = max(int(read) - extracted, 0)
        if extracted + rejected != int(read):
            mismatches.append(name)
    check = _check(
        "record_counts", "Record Count Reconciliation", "Extracted datasets",
        "Verify extraction completeness", "Critical",
        "records extracted + records rejected = records read for every dataset",
        not mismatches,
        "all datasets reconcile" if not mismatches
        else f"mismatched datasets: {mismatches}",
    )
    validation["checks"].append(check)
    if check["status"] == "FAIL":
        validation["errors"].append(check["detail"])
        validation["status"] = "FAIL"
    return validation
