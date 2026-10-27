"""TRN-002: apply cleaning rules C-01 to C-06 and quarantine rejected records.

Rules implemented here (Section 3):
    C-01  required values             -> quarantine the affected record
    C-02  whitespace cleanup          -> trim/collapse and log the modification
    C-03  duplicate identifiers       -> quarantine every conflicting record
    C-04  invalid values              -> quarantine with rule ID and reason
    C-05  orphan relationships        -> quarantine with the missing reference
    C-06  invalid characters          -> correct only under the approved rule,
                                         otherwise quarantine

The parent reference set for C-05 is the approved parent records in the current
handover plus the approved parent reference published with it. Stage 2 does not
connect to the source database, and an unresolved parent is reported instead of
being silently ignored (Section 5 and Section 11).
Standardization rules S-01 to S-07 are applied by TRN-003 after cleaning.
"""

from __future__ import annotations

from collections import Counter

from trn000_config import (
    DATASETS,
    PROCESSING_ORDER,
    approved_reference_keys,
    normalize_space,
    quarantine_row,
    recover_condition_name,
    to_int,
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


def _normalize_whitespace(records: dict[str, list[dict]], rules: Counter) -> dict:
    """C-02: trim and collapse whitespace on every text value."""
    normalized: dict[str, list[dict]] = {}
    for name, rows in records.items():
        output = []
        for row in rows:
            result = {}
            changed = False
            for key, value in row.items():
                text = normalize_space(value)
                if text != value:
                    changed = True
                result[key] = text
            result["_modified"] = changed
            if changed:
                rules["C-02"] += 1
            output.append(result)
        normalized[name] = output
    return normalized


def _identifiers(dataset: str, row: dict, context: dict, quarantine: list[dict],
                 rules: Counter, rejected: Counter) -> dict | None:
    """Validate and convert the primary key and foreign keys (C-01, S-04)."""
    spec = DATASETS[dataset]
    columns = [spec["primary_key"], *spec.get("foreign_keys", {})]
    values = {}
    for column in columns:
        raw = normalize_space(row.get(column))
        if raw == "":
            _reject(context, dataset, row, quarantine, rules, rejected, "C-01", column,
                    "MISSING_REQUIRED_VALUE", f"{column} is a required value")
            return None
        value = to_int(raw)
        if value is None:
            _reject(context, dataset, row, quarantine, rules, rejected, "S-04", column,
                    "INVALID_IDENTIFIER", f"{column} is not an integer-compatible identifier")
            return None
        values[column] = value
    return values


def _clean_puroks(rows: list[dict], parents: dict, context: dict, quarantine: list[dict],
                  rules: Counter, rejected: Counter) -> list[dict]:
    retained = []
    for row in rows:
        ids = _identifiers("puroks", row, context, quarantine, rules, rejected)
        if ids is None:
            continue

        name = normalize_space(row.get("name"))
        if name == "":
            _reject(context, "puroks", row, quarantine, rules, rejected, "C-01", "name",
                    "MISSING_REQUIRED_VALUE", "name is a required value")
            continue
        if not any(character.isalpha() for character in name):
            _reject(context, "puroks", row, quarantine, rules, rejected, "C-06", "name",
                    "INVALID_PUROK_NAME",
                    "name contains no alphabetic character and is not a valid purok name")
            continue

        retained.append({
            "purok_id": ids["purok_id"],
            "name": name,
            "_modified": row.get("_modified", False),
        })
    return retained


def _clean_residents(rows: list[dict], parents: dict, context: dict, quarantine: list[dict],
                     rules: Counter, rejected: Counter) -> list[dict]:
    retained = []
    purok_ids = parents.get("puroks", set())
    for row in rows:
        ids = _identifiers("residents", row, context, quarantine, rules, rejected)
        if ids is None:
            continue

        risk_level = normalize_space(row.get("risk_level"))
        if risk_level == "":
            _reject(context, "residents", row, quarantine, rules, rejected, "C-01",
                    "risk_level", "MISSING_REQUIRED_VALUE", "risk_level is a required value")
            continue
        if ids["purok_id"] not in purok_ids:
            _reject(context, "residents", row, quarantine, rules, rejected, "C-05",
                    "purok_id", "ORPHAN_FOREIGN_KEY",
                    f"purok_id {ids['purok_id']} has no approved purok reference")
            continue

        retained.append({
            "resident_id": ids["resident_id"],
            "purok_id": ids["purok_id"],
            "risk_level": risk_level,
            "_modified": row.get("_modified", False),
        })
    return retained


def _clean_conditions(rows: list[dict], parents: dict, context: dict, quarantine: list[dict],
                      rules: Counter, rejected: Counter) -> list[dict]:
    retained = []
    resident_ids = parents.get("residents", set())
    for row in rows:
        ids = _identifiers("resident_chronic_conditions", row, context, quarantine,
                           rules, rejected)
        if ids is None:
            continue

        raw_name = normalize_space(row.get("condition_name"))
        if raw_name == "":
            _reject(context, "resident_chronic_conditions", row, quarantine, rules, rejected,
                    "C-01", "condition_name", "MISSING_REQUIRED_VALUE",
                    "condition_name is a required value")
            continue
        if normalize_space(row.get("created_at")) == "":
            _reject(context, "resident_chronic_conditions", row, quarantine, rules, rejected,
                    "C-01", "created_at", "MISSING_REQUIRED_VALUE",
                    "created_at is a required value")
            continue

        name, embedded = recover_condition_name(raw_name)
        if embedded:
            rules["C-06"] += 1
        if not name or sum(1 for character in name if character.isalpha()) < 3 \
                or any(character.isdigit() for character in name):
            _reject(context, "resident_chronic_conditions", row, quarantine, rules, rejected,
                    "C-04", "condition_name", "INVALID_CONDITION_NAME",
                    "condition_name is a placeholder or has no usable alphabetic name")
            continue
        if ids["resident_id"] not in resident_ids:
            _reject(context, "resident_chronic_conditions", row, quarantine, rules, rejected,
                    "C-05", "resident_id", "ORPHAN_FOREIGN_KEY",
                    f"resident_id {ids['resident_id']} has no approved resident reference")
            continue

        retained.append({
            "condition_id": ids["condition_id"],
            "resident_id": ids["resident_id"],
            "condition_name": name,
            "created_at": normalize_space(row.get("created_at")),
            "_modified": row.get("_modified", False) or embedded or name != raw_name,
        })
    return retained


def _clean_schedules(rows: list[dict], parents: dict, context: dict, quarantine: list[dict],
                     rules: Counter, rejected: Counter) -> list[dict]:
    retained = []
    resident_ids = parents.get("residents", set())
    for row in rows:
        ids = _identifiers("schedules", row, context, quarantine, rules, rejected)
        if ids is None:
            continue

        date_value = normalize_space(row.get("date"))
        status = normalize_space(row.get("status"))
        if date_value == "" or status == "":
            column = "date" if date_value == "" else "status"
            _reject(context, "schedules", row, quarantine, rules, rejected, "C-01", column,
                    "MISSING_REQUIRED_VALUE", f"{column} is a required value")
            continue
        if ids["resident_id"] not in resident_ids:
            _reject(context, "schedules", row, quarantine, rules, rejected, "C-05",
                    "resident_id", "ORPHAN_FOREIGN_KEY",
                    f"resident_id {ids['resident_id']} has no approved resident reference")
            continue

        retained.append({
            "schedule_id": ids["schedule_id"],
            "resident_id": ids["resident_id"],
            "date": date_value,
            "status": status,
            "_modified": row.get("_modified", False),
        })
    return retained


_CLEANERS = {
    "puroks": _clean_puroks,
    "residents": _clean_residents,
    "resident_chronic_conditions": _clean_conditions,
    "schedules": _clean_schedules,
}


def _resolve_duplicates(dataset: str, rows: list[dict], context: dict,
                        quarantine: list[dict], rules: Counter) -> tuple[list[dict], int]:
    """C-03: quarantine conflicting primary keys when no winner rule is approved."""
    primary_key = DATASETS[dataset]["primary_key"]
    groups: dict[object, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[primary_key], []).append(row)

    retained = []
    duplicate_count = 0
    for key, group in groups.items():
        if len(group) == 1:
            retained.append(group[0])
            continue
        duplicate_count += len(group)
        rules["C-03"] += len(group)
        for row in group:
            quarantine.append(quarantine_row(
                context, dataset, key, "C-03", primary_key, key,
                "DUPLICATE_PRIMARY_KEY",
                f"{primary_key} {key} occurs {len(group)} times and no approved "
                "authoritative-record rule resolves the conflict",
            ))
    return retained, duplicate_count


def clean(records: dict[str, list[dict]], context: dict,
          reference: dict | None = None) -> dict:
    """Return cleaned records, quarantine rows, and per-rule counters."""
    quarantine: list[dict] = []
    rules: Counter = Counter()
    rejected: Counter = Counter()
    duplicates: Counter = Counter()
    cleaned: dict[str, list[dict]] = {}
    reference = reference or {}

    normalized = _normalize_whitespace(records, rules)
    parents: dict[str, set] = {}
    present_parent_keys: dict[str, set] = {}
    for name in ("puroks", "residents"):
        key = DATASETS[name]["primary_key"]
        present_parent_keys[name] = {
            value for row in normalized[name]
            if (value := to_int(row.get(key))) is not None
        }

    for name in PROCESSING_ORDER:
        cleaner = _CLEANERS[name]
        rows = cleaner(normalized[name], parents, context, quarantine, rules, rejected)
        rows, duplicate_count = _resolve_duplicates(
            name, rows, context, quarantine, rules
        )
        duplicates[name] = duplicate_count
        cleaned[name] = rows
        retained_keys = {row[DATASETS[name]["primary_key"]] for row in rows}
        parents[name] = retained_keys
        if name in ("puroks", "residents"):
            # A parent present in this batch but quarantined here is not
            # "missing"; it must not be resurrected from the reference set.
            rejected_in_batch = present_parent_keys[name] - retained_keys
            parents[name] |= (
                approved_reference_keys(reference, name) - rejected_in_batch
            )

    modified = Counter({
        name: sum(1 for row in rows if row.get("_modified"))
        for name, rows in cleaned.items()
    })

    return {
        "records": cleaned,
        "quarantine": quarantine,
        "rules": rules,
        "rejected": rejected,
        "duplicates": duplicates,
        "modified": modified,
    }
