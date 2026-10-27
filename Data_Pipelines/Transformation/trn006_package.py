"""TRN-006: publish contracted outputs atomically and record the handover.

Section 6.1 defines the output files; Section 8.1 defines the metadata fields;
Section 9.1 defines log, quarantine, and audit retention; Section 10.3 defines
the handover package. No database load is performed by this stage.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from trn000_config import (
    AUDIT_DIR,
    CHECKPOINT_DIR,
    CODE_VERSION,
    DATASETS,
    LOG_DIR,
    OUTPUT_DIR,
    OUTPUT_FILES,
    PROFILE_DIR,
    QUARANTINE_COLUMNS,
    QUARANTINE_DIR,
    RULES_VERSION,
    append_event,
    iso_timestamp,
    sha256_file,
    utc_now,
    write_json,
)

STATUS_FOR_VALIDATION = {"PASS": "SUCCESS", "WARNING": "WARNING", "FAIL": "FAILED"}


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _validation_summary(validation: dict) -> dict:
    return {check["id"]: check["status"] for check in validation["checks"]}


def build_metadata(context: dict, tables: dict, validation: dict, rules: dict) -> dict:
    """Build the Section 8.1 metadata record, including one row per file."""
    records_read = context["records_read"]
    records_rejected = context["records_rejected"]
    records_modified = context["records_modified"]
    rules_applied = {key: value for key, value in sorted(rules.items()) if value}
    validation_results = _validation_summary(validation)

    files = []
    for name in DATASETS:
        entry = {
            "file_name": DATASETS[name]["file"],
            "records_read": records_read.get(name, 0),
            "records_output": len(tables[name]),
            "records_rejected": records_rejected.get(name, 0),
            "records_modified": records_modified.get(name, 0),
            "validation_results": validation_results,
        }
        files.append(entry)

    return {
        "run_id": context["run_id"],
        "parent_run_id": context["parent_run_id"],
        "batch_id": context["batch_id"],
        "batch_window": context["batch_window"],
        "file_name": "ALL",
        "start_timestamp": context["start_timestamp"],
        "end_timestamp": context["end_timestamp"],
        "status": STATUS_FOR_VALIDATION[validation["status"]],
        "records_read": dict(records_read),
        "records_output": {name: len(tables[name]) for name in DATASETS},
        "records_rejected": dict(records_rejected),
        "records_duplicates_excluded": dict(validation["metrics"]["records_duplicates_excluded"]),
        "records_business_excluded": validation["metrics"]["records_business_excluded"],
        "records_modified": dict(records_modified),
        "reference_parent_counts": dict(context.get("reference_counts", {})),
        "rules_applied": rules_applied,
        "validation_results": validation_results,
        "error_code": context.get("error_code"),
        "error_message": context.get("error_message"),
        "duration_seconds": context["duration_seconds"],
        "code_version": CODE_VERSION,
        "rules_version": RULES_VERSION,
        "decision": validation["decision"],
        "handover_status": validation["handover_status"],
        "files": files,
    }


def package(context: dict, tables: dict, validation: dict, profile: dict, rules: dict,
            quarantine: list[dict], business_rules: dict, join_cardinality: dict) -> dict:
    """Publish the batch atomically, then write logs, metadata, and the manifest."""
    batch_id = context["batch_id"]
    run_id = context["run_id"]
    target = Path(OUTPUT_DIR) / batch_id
    temp = Path(OUTPUT_DIR) / f".tmp_{batch_id}"

    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)

    metadata = build_metadata(context, tables, validation, rules)
    try:
        for name in DATASETS:
            _write_csv(
                temp / OUTPUT_FILES[name]["file"],
                tables[name],
                OUTPUT_FILES[name]["columns"],
            )

        write_json(temp / "metadata.json", metadata)
        write_json(temp / "validation_report.json", validation)

        files = {}
        for name in DATASETS:
            file_name = OUTPUT_FILES[name]["file"]
            path = temp / file_name
            files[name] = {
                "file_name": file_name,
                "rows": len(tables[name]),
                "sha256": sha256_file(path),
            }

        manifest = {
            "batch_id": batch_id,
            "run_id": run_id,
            "parent_run_id": context["parent_run_id"],
            "batch_window": context["batch_window"],
            "generated_at": iso_timestamp(utc_now()),
            "code_version": CODE_VERSION,
            "rules_version": RULES_VERSION,
            "input_directory": context.get("input_dir"),
            "output_directory": str(target),
            "status": metadata["status"],
            "decision": validation["decision"],
            "handover_status": validation["handover_status"],
            "counts": {
                "records_read": metadata["records_read"],
                "records_output": metadata["records_output"],
                "records_rejected": metadata["records_rejected"],
                "records_modified": metadata["records_modified"],
                "records_duplicates_excluded": validation["metrics"][
                    "records_duplicates_excluded"
                ],
                "records_business_excluded": validation["metrics"][
                    "records_business_excluded"
                ],
                "overall_rejection_rate": validation["metrics"][
                    "overall_rejection_rate"
                ],
            },
            "business_rules": business_rules,
            "join_cardinality": join_cardinality,
            "reference_parent_counts": context.get("reference_counts", {}),
            "quarantine": {
                "file": str(Path(QUARANTINE_DIR) / f"{batch_id}_quarantine.csv"),
                "records": len(quarantine),
            },
            "schema": {
                name: OUTPUT_FILES[name]["columns"] for name in DATASETS
            },
            "files": files,
        }
        write_json(temp / "manifest.json", manifest)

        (temp / "README.md").write_text(
            "# CitiCare Stage 2 Transformation Output\n\n"
            f"- batch_id: `{batch_id}`\n"
            f"- run_id: `{run_id}`\n"
            f"- parent_run_id: `{context['parent_run_id']}`\n"
            f"- batch_window: `{context['batch_window']}`\n"
            f"- decision: `{validation['decision']}`\n"
            f"- handover_status: `{validation['handover_status']}`\n"
            f"- code_version: `{CODE_VERSION}`\n"
            f"- rules_version: `{RULES_VERSION}`\n\n"
            "Do not load this package unless `handover_status` is `APPROVED`.\n",
            encoding="utf-8",
        )

        # Idempotent rerun: replace any previous attempt of the same batch.
        if target.exists():
            shutil.rmtree(target)
        temp.rename(target)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise

    # Section 9.1: rejected records are retained outside the published output.
    _write_csv(
        Path(QUARANTINE_DIR) / f"{batch_id}_quarantine.csv",
        quarantine,
        QUARANTINE_COLUMNS,
    )
    write_json(Path(PROFILE_DIR) / f"profile_{batch_id}.json", profile)

    audit_dir = Path(AUDIT_DIR) / context["run_date"][:4]
    write_json(audit_dir / f"{batch_id}_{run_id}_metadata.json", metadata)
    write_json(audit_dir / f"{batch_id}_{run_id}_manifest.json", manifest)
    write_json(audit_dir / f"{batch_id}_{run_id}_validation_report.json", validation)
    write_json(audit_dir / f"{batch_id}_{run_id}_profile.json", profile)

    append_event(
        Path(LOG_DIR) / "transform.log",
        "INFO" if validation["status"] == "PASS" else "WARNING",
        run_id, "transform", "batch_completed",
        {
            "parent_run_id": context["parent_run_id"],
            "batch_id": batch_id,
            "batch_window": context["batch_window"],
            "records_read": metadata["records_read"],
            "records_output": metadata["records_output"],
            "records_rejected": metadata["records_rejected"],
            "records_modified": metadata["records_modified"],
            "rules_applied": metadata["rules_applied"],
            "quarantined": len(quarantine),
            "decision": validation["decision"],
            "handover_status": validation["handover_status"],
            "code_version": CODE_VERSION,
            "rules_version": RULES_VERSION,
            "duration_seconds": context["duration_seconds"],
        },
    )

    for check in validation["checks"]:
        level = {"PASS": "INFO", "WARNING": "WARNING", "FAIL": "ERROR"}[check["status"]]
        append_event(
            Path(LOG_DIR) / "validation.log", level, run_id, "validate", "check",
            {
                "check_id": check["id"],
                "check_name": check["name"],
                "target": check["target"],
                "check_status": check["status"],
                "severity": check["severity"],
                "expected": check["expected"],
                "actual": check["actual"],
            },
        )
    append_event(
        Path(LOG_DIR) / "validation.log",
        "INFO" if validation["status"] == "PASS" else "WARNING",
        run_id, "validate", "validation_completed",
        {
            "batch_id": batch_id,
            "validation_status": validation["status"],
            "decision": validation["decision"],
            "check_count": len(validation["checks"]),
            "warning_count": sum(
                1 for check in validation["checks"] if check["status"] == "WARNING"
            ),
            "error_count": sum(
                1 for check in validation["checks"] if check["status"] == "FAIL"
            ),
        },
    )

    append_event(
        Path(LOG_DIR) / "handover.log",
        "INFO" if validation["handover_status"] == "APPROVED" else "WARNING",
        run_id, "handover", "acceptance_decision",
        {
            "parent_run_id": context["parent_run_id"],
            "batch_id": batch_id,
            "decision": validation["decision"],
            "handover_status": validation["handover_status"],
            "validation_status": validation["status"],
            "output_directory": str(target),
        },
    )

    write_json(Path(CHECKPOINT_DIR) / f"{batch_id}.json", {
        "batch_id": batch_id,
        "last_successful_step": "package",
        "run_id": run_id,
        "status": metadata["status"],
        "updated_at": iso_timestamp(utc_now()),
    })

    return manifest
