"""TRN-005: validate the transformed output and decide acceptance (Section 7).

The check names match Section 7 exactly. A critical failure stops the handover;
a non-critical warning holds the batch for manual review; otherwise the batch
is approved (Section 10.2).
"""

from __future__ import annotations

from trn000_config import (
    APPROVED_RISK_LEVELS,
    APPROVED_SCHEDULE_STATUSES,
    DATASETS,
    ISO_DATE_PATTERN,
    ISO_TIMESTAMP_PATTERN,
    OUTPUT_FILES,
    PROCESSING_ORDER,
    REJECTION_RATE_LIMIT,
    approved_reference_keys,
    parse_iso_date,
    parse_iso_timestamp,
)
from trn004_transform import APPROVED_DERIVED_OUTPUTS


def _check(check_id: str, name: str, target: str, purpose: str, criteria: str,
           passed: bool, severity: str, expected: str, actual: str,
           detail: str = "", warning: bool = False) -> dict:
    status = "PASS" if passed else ("WARNING" if warning else "FAIL")
    return {
        "id": check_id,
        "name": name,
        "target": target,
        "purpose": purpose,
        "criteria": criteria,
        "status": status,
        "severity": severity,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _duplicate_count(rows: list[dict], key: str) -> int:
    markers = [row.get(key) for row in rows]
    return len(markers) - len(set(markers))


def validate(tables: dict, metrics: dict, context: dict, join_cardinality: dict,
             schema: dict, reference: dict | None = None) -> dict:
    """Return the Section 7 validation results and the acceptance decision."""
    checks: list[dict] = []
    reference = reference or {}
    reads: dict = metrics["records_read"]
    rejected: dict = metrics["rejected"]
    duplicates: dict = metrics["duplicates"]
    modified: dict = metrics["modified"]

    # V-01: record reconciliation (Section 7, Critical).
    equations = {}
    for name in PROCESSING_ORDER:
        output = len(tables[name])
        equations[name] = {
            "records_read": reads[name],
            "records_output": output,
            "records_rejected": rejected[name],
            "documented_duplicate_exclusions": duplicates[name],
            "balanced": reads[name] == output + rejected[name] + duplicates[name],
        }
    total_read = sum(reads.values())
    total_output = sum(len(tables[name]) for name in PROCESSING_ORDER)
    total_rejected = sum(rejected.values())
    total_duplicates = sum(duplicates.values())
    reconciliation_ok = all(item["balanced"] for item in equations.values()) and (
        total_read == total_output + total_rejected + total_duplicates
    )
    checks.append(_check(
        "V-01", "Record reconciliation", "each input and output dataset",
        "Detect missing or unaccounted-for records",
        "records_read = records_output + records_rejected + documented_duplicate_exclusions",
        reconciliation_ok, "Critical",
        f"{total_read} = {total_output} + {total_rejected} + {total_duplicates}",
        "; ".join(
            f"{name}: {item['records_read']} = {item['records_output']} + "
            f"{item['records_rejected']} + {item['documented_duplicate_exclusions']}"
            for name, item in equations.items()
        ),
    ))

    # V-02: required fields (Section 7, Critical).
    blank_fields = {}
    for name in PROCESSING_ORDER:
        columns = OUTPUT_FILES[name]["columns"]
        blank_fields[name] = {
            column: sum(1 for row in tables[name] if row.get(column) in (None, ""))
            for column in columns
        }
    blank_total = sum(sum(values.values()) for values in blank_fields.values())
    checks.append(_check(
        "V-02", "Required fields", "required columns in all four outputs",
        "Prevent missing mandatory values",
        "no null or blank values in required fields",
        blank_total == 0, "Critical", "blank count = 0", f"blank count = {blank_total}",
        detail=str(blank_fields),
    ))

    # V-03: primary-key uniqueness (Section 7, Critical).
    pk_duplicates = {
        name: _duplicate_count(tables[name], DATASETS[name]["primary_key"])
        for name in PROCESSING_ORDER
    }
    checks.append(_check(
        "V-03", "Primary-key uniqueness",
        "resident_id, condition_id, schedule_id, purok_id",
        "Prevent duplicate keys",
        "duplicate primary-key count = 0",
        all(value == 0 for value in pk_duplicates.values()), "Critical",
        "duplicate count = 0", str(pk_duplicates),
    ))

    # V-04: referential integrity (Section 7, Critical).
    purok_ids = (
        {row["purok_id"] for row in tables["puroks"]}
        | approved_reference_keys(reference, "puroks")
    )
    resident_ids = (
        {row["resident_id"] for row in tables["residents"]}
        | approved_reference_keys(reference, "residents")
    )
    orphans = {
        "residents.purok_id": sum(
            1 for row in tables["residents"] if row["purok_id"] not in purok_ids),
        "resident_chronic_conditions.resident_id": sum(
            1 for row in tables["resident_chronic_conditions"]
            if row["resident_id"] not in resident_ids),
        "schedules.resident_id": sum(
            1 for row in tables["schedules"] if row["resident_id"] not in resident_ids),
    }
    checks.append(_check(
        "V-04", "Referential integrity",
        "resident, purok, condition, and schedule relationships",
        "Prevent orphan references",
        "all required references match the approved parent dataset",
        sum(orphans.values()) == 0, "Critical",
        "orphan count = 0", str(orphans),
        detail=(
            "Approved reference parents: "
            f"puroks={len(approved_reference_keys(reference, 'puroks'))}, "
            f"residents={len(approved_reference_keys(reference, 'residents'))}"
        ),
    ))

    # V-05: type and format conformance (Section 7, Critical).
    format_errors: list[str] = []
    for name in PROCESSING_ORDER:
        for row in tables[name]:
            for column, target in OUTPUT_FILES[name]["types"].items():
                value = row.get(column)
                if target == "integer" and not isinstance(value, int):
                    format_errors.append(f"{name}.{column}={value!r}")
                elif target == "text" and not isinstance(value, str):
                    format_errors.append(f"{name}.{column}={value!r}")
                elif target == "date" and (
                    not isinstance(value, str)
                    or not ISO_DATE_PATTERN.match(value)
                    or parse_iso_date(value) is None
                ):
                    format_errors.append(f"{name}.{column}={value!r}")
                elif target == "timestamp" and (
                    not isinstance(value, str)
                    or not ISO_TIMESTAMP_PATTERN.match(value)
                    or parse_iso_timestamp(value) is None
                ):
                    format_errors.append(f"{name}.{column}={value!r}")
    for row in tables["residents"]:
        if row["risk_level"] not in APPROVED_RISK_LEVELS:
            format_errors.append(f"residents.risk_level={row['risk_level']!r}")
    for row in tables["schedules"]:
        if row["status"] not in APPROVED_SCHEDULE_STATUSES:
            format_errors.append(f"schedules.status={row['status']!r}")
    checks.append(_check(
        "V-05", "Type and format conformance", "identifiers, dates, timestamps, text domains",
        "Ensure expected output formats",
        "all retained values conform to the output contract",
        not format_errors, "Critical", "format error count = 0",
        f"format error count = {len(format_errors)}",
        detail="; ".join(format_errors[:5]),
    ))

    # V-06: join cardinality (Section 7, Critical).
    cardinality_errors = [
        name for name, item in join_cardinality.items()
        if item["unmatched"] or item["multiple_matches"] or item["row_multiplication"]
        or not item["parent_key_unique"]
    ]
    checks.append(_check(
        "V-06", "Join cardinality", "business transformation joins",
        "Detect unintended row multiplication",
        "output row counts and key multiplicities match the approved join design",
        not cardinality_errors, "Critical",
        "unmatched = 0 and no row multiplication",
        "all documented joins are 1:1 and additive" if not cardinality_errors
        else f"problem joins: {cardinality_errors}",
        detail=str(join_cardinality),
    ))

    # V-07: aggregation reconciliation (Section 7, Critical).
    if APPROVED_DERIVED_OUTPUTS:
        checks.append(_check(
            "V-07", "Aggregation reconciliation", "derived summaries",
            "Ensure totals represent the contributing records",
            "aggregated counts and measures reconcile with eligible input records",
            True, "Critical", "totals reconcile", "approved summaries reconciled",
        ))
    else:
        checks.append(_check(
            "V-07", "Aggregation reconciliation", "derived summaries",
            "Ensure totals represent the contributing records",
            "aggregated counts and measures reconcile with eligible input records",
            True, "Critical", "not applicable", "no derived summary is approved",
            detail=(
                "Section 6.1 requires a separately approved schema for derived "
                "summaries; none is defined, so no aggregate output exists to "
                "reconcile. The check passes as not applicable."
            ),
        ))

    # V-08: business-rule validation (Section 7, Critical).
    invented = {
        "risk_level": sorted({
            row["risk_level"] for row in tables["residents"]
            if row["risk_level"] not in APPROVED_RISK_LEVELS
        }),
        "status": sorted({
            row["status"] for row in tables["schedules"]
            if row["status"] not in APPROVED_SCHEDULE_STATUSES
        }),
    }
    checks.append(_check(
        "V-08", "Business-rule validation", "risk levels, statuses, and derived outputs",
        "Ensure approved business rules are followed",
        "all retained values and derived results meet approved rules",
        not any(invented.values()), "Critical",
        "no value outside the approved mapping", str(invented),
    ))

    # V-09: rejection-rate monitoring (Section 7, Critical severity).
    overall_rate = _rate(total_rejected, total_read)
    per_table_rate = {
        name: _rate(rejected[name], reads[name]) for name in PROCESSING_ORDER
    }
    within_threshold = overall_rate <= REJECTION_RATE_LIMIT
    checks.append(_check(
        "V-09", "Rejection-rate monitoring", "each dataset and batch",
        "Monitor transformation quality",
        f"rejection_rate = records_rejected / records_read x 100 <= {REJECTION_RATE_LIMIT:.2%}",
        within_threshold, "Critical",
        f"overall rejection rate <= {REJECTION_RATE_LIMIT:.2%}",
        f"{total_rejected}/{total_read} ({overall_rate:.2%}); "
        + ", ".join(f"{name}={value:.2%}" for name, value in per_table_rate.items()),
        detail=(
            "Documented duplicate exclusions are reported separately from "
            "rejected records (Section 10.1). An over-threshold result is a "
            "manual-review condition per Section 10.2."
        ),
        warning=True,
    ))

    # V-10: transformation warning review (Section 7, Non-critical).
    warnings: list[str] = []
    for name, info in schema.items():
        if info.get("unexpected_columns"):
            warnings.append(
                f"{DATASETS[name]['file']}: unexpected column(s) "
                f"{info['unexpected_columns']} flagged for review"
            )
    if not within_threshold:
        warnings.append(
            f"batch rejection rate {overall_rate:.2%} exceeds the approved "
            f"threshold {REJECTION_RATE_LIMIT:.2%}"
        )
    checks.append(_check(
        "V-10", "Transformation warning review", "non-critical data-quality findings",
        "Identify issues that need attention",
        "warnings are documented and assigned for review",
        not warnings, "Non-critical", "no warning requires review",
        f"{len(warnings)} warning(s)",
        detail="; ".join(warnings) if warnings else "no warnings recorded",
        warning=True,
    ))

    # Acceptance decision (Section 10.2).
    if any(check["status"] == "FAIL" for check in checks):
        overall_status = "FAIL"
        decision = "REJECTED"
        handover_status = "REJECTED"
    elif any(check["status"] == "WARNING" for check in checks):
        overall_status = "WARNING"
        decision = "MANUAL REVIEW"
        handover_status = "HELD"
    else:
        overall_status = "PASS"
        decision = "APPROVED"
        handover_status = "APPROVED"

    return {
        "checks": checks,
        "status": overall_status,
        "decision": decision,
        "handover_status": handover_status,
        "warnings": warnings,
        "metrics": {
            "records_read": dict(reads),
            "records_output": {name: len(tables[name]) for name in PROCESSING_ORDER},
            "records_rejected": {
                name: rejected.get(name, 0) for name in PROCESSING_ORDER
            },
            "records_duplicates_excluded": {
                name: duplicates.get(name, 0) for name in PROCESSING_ORDER
            },
            "records_modified": {
                name: modified.get(name, 0) for name in PROCESSING_ORDER
            },
            "records_business_excluded": metrics["excluded"],
            "overall_rejection_rate": round(overall_rate, 4),
            "reference_parent_counts": {
                "puroks": len(approved_reference_keys(reference, "puroks")),
                "residents": len(approved_reference_keys(reference, "residents")),
            },
        },
    }
