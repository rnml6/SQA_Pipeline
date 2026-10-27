"""TRN-004: apply the approved business transformation rules B-01 to B-05.

Section 5 makes the enrichment and summary rules conditional ("when required",
"if required by the output contract"). Section 6.1 states that any derived
summary output needs a separately approved schema before implementation, and
none is defined. The approved output contract is therefore the four cleaned
datasets themselves. This module:

* projects retained records onto the contracted output columns,
* validates the B-01 resident-to-purok join and its cardinality,
* records that B-02, B-03 and B-04 have no approved output schema, and
* applies B-05 by keeping failed records out of the outputs while the
  quarantine file preserves them with a rule ID and reason.
"""

from __future__ import annotations

from collections import Counter

from trn000_config import (
    DATASETS,
    OUTPUT_FILES,
    PROCESSING_ORDER,
    approved_reference_keys,
)

# Section 6.1: a derived summary must have a separately approved schema. No
# such schema is currently approved, so summary rules are deliberately not
# emitted instead of inventing one.
APPROVED_DERIVED_OUTPUTS: dict[str, str] = {}


def _join_cardinality(child_rows: list[dict], child_key: str,
                      parent_rows: list[dict], parent_key: str) -> dict:
    """Measure a documented join: matches, unmatched rows, and multiplication."""
    parent_counts = Counter(row[parent_key] for row in parent_rows)
    matched = 0
    multiple = 0
    for row in child_rows:
        count = parent_counts.get(row[child_key], 0)
        if count:
            matched += 1
        if count > 1:
            multiple += 1
    return {
        "child_rows": len(child_rows),
        "parent_rows": len(parent_rows),
        "matched": matched,
        "unmatched": len(child_rows) - matched,
        "multiple_matches": multiple,
        "parent_key_unique": all(count <= 1 for count in parent_counts.values()),
        "row_multiplication": len(child_rows) - matched + multiple,
    }


def _parent_rows(reference: dict, dataset: str, output_rows: list[dict],
                 key: str) -> list[dict]:
    """Combine batch parents with the approved parent reference for joins."""
    keys = {row[key] for row in output_rows}
    keys |= approved_reference_keys(reference, dataset)
    return [{key: value} for value in sorted(keys)]


def transform(records: dict[str, list[dict]], context: dict,
              excluded_count: int, reference: dict | None = None) -> dict:
    """Return the contracted output tables, join findings, and business rules."""
    reference = reference or {}
    tables = {}
    for name in PROCESSING_ORDER:
        columns = OUTPUT_FILES[name]["columns"]
        primary_key = DATASETS[name]["primary_key"]
        tables[name] = [
            {column: row[column] for column in columns}
            for row in sorted(records[name], key=lambda item: item[primary_key])
        ]

    purok_parents = _parent_rows(
        reference, "puroks", tables["puroks"], "purok_id"
    )
    resident_parents = _parent_rows(
        reference, "residents", tables["residents"], "resident_id"
    )
    join_cardinality = {
        "residents_to_puroks": _join_cardinality(
            tables["residents"], "purok_id", purok_parents, "purok_id"
        ),
        "conditions_to_residents": _join_cardinality(
            tables["resident_chronic_conditions"], "resident_id",
            resident_parents, "resident_id"
        ),
        "schedules_to_residents": _join_cardinality(
            tables["schedules"], "resident_id", resident_parents, "resident_id"
        ),
    }

    business_rules = {
        "B-01": {
            "status": "VALIDATED",
            "detail": (
                "Residents are joined to the approved purok reference using "
                "purok_id to verify referential integrity and join cardinality. "
                "The reference combines the current batch with the approved "
                "parent dataset published with the handover. No purok attribute "
                "is added because the approved output contract does not request "
                "enrichment."
            ),
        },
        "B-02": {
            "status": "NOT_REQUIRED",
            "detail": (
                "A resident chronic-condition count is only produced when the "
                "output contract requires it; no approved derived summary "
                "schema exists, so no count is emitted."
            ),
        },
        "B-03": {
            "status": "NOT_REQUIRED",
            "detail": (
                "A schedule or consultation summary is only produced when "
                "required; no approved derived summary schema exists."
            ),
        },
        "B-04": {
            "status": "NOT_REQUIRED",
            "detail": (
                "A purok-level summary is only produced when required; no "
                "approved derived summary schema exists."
            ),
        },
        "B-05": {
            "status": "APPLIED",
            "excluded_records": excluded_count,
            "detail": (
                "Records that failed a mandatory rule are excluded from the "
                "business-ready outputs and preserved in the quarantine file "
                "with a rule ID and reason."
            ),
        },
    }

    return {
        "tables": tables,
        "join_cardinality": join_cardinality,
        "business_rules": business_rules,
        "rules": Counter({"B-05": excluded_count}),
    }
