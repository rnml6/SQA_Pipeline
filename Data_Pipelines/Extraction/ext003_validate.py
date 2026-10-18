"""EXT-003: validate source files, schema, types, keys, and relationships."""

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


def validate(records):
    errors = []
    warnings = []
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            errors.append(detail)

    for dataset, (primary_key, required) in DATASETS.items():
        rows = records.get(dataset)
        check(f"dataset:{dataset}", rows is not None, f"Dataset present: {dataset}")
        if rows is None:
            continue
        columns = set(rows[0]) if rows else set(required)
        check(f"snake_case:columns:{dataset}", all(SNAKE_CASE.fullmatch(column) for column in columns), f"{dataset} column names follow snake_case")
        missing = set(required) - columns
        check(f"columns:{dataset}", not missing, f"{dataset} required columns present")
        extra = sorted(columns - set(required) - {"created_at", "updated_at"})
        if extra:
            warnings.append(f"{dataset} has additional columns: {extra}")

        keys = [row.get(primary_key) for row in rows]
        check(f"primary_key:{dataset}", all(not _blank(value) for value in keys) and len(keys) == len(set(keys)), f"{dataset}.{primary_key} values are present and unique")
        for column in required:
            blanks = sum(_blank(row.get(column)) for row in rows)
            if column in OPTIONAL_COLUMNS.get(dataset, set()):
                check(f"required_values:{dataset}.{column}", True, f"{dataset}.{column} allows null values")
            else:
                check(f"required_values:{dataset}.{column}", blanks == 0, f"{dataset}.{column} has {blanks} blank values")
            invalid_types = sum(not _valid_type(column, row.get(column)) for row in rows if not _blank(row.get(column)))
            check(f"data_type:{dataset}.{column}", invalid_types == 0, f"{dataset}.{column} has {invalid_types} invalid values")

    resident_ids = {row.get("resident_id") for row in records.get("residents", [])}
    purok_ids = {row.get("purok_id") for row in records.get("puroks", [])}
    check("foreign_key:resident_id", all(row.get("resident_id") in resident_ids for rows in records.values() for row in rows if "resident_id" in row), "resident_id foreign keys are available")
    check("foreign_key:purok_id", all(row.get("purok_id") in purok_ids for row in records.get("residents", [])), "residents.purok_id foreign keys are available")
    return {"status": "FAIL" if errors else "PASS", "checks": checks, "errors": errors, "warnings": warnings}
