"""Run the CitiCare Stage 2 transformation.

Pipeline (Section 1.4 processing order):

    1. validate the extraction handover and required input files
    2. profile all four datasets
    3. clean and standardize puroks and residents
    4. clean and standardize resident chronic conditions and schedules
    5. validate primary keys, foreign keys, and relationships
    6. apply the approved business transformation rules
    7. validate and reconcile transformed outputs
    8. package approved outputs and metadata for the Data Loading Stage

The batch is idempotent: rerunning the same extraction batch replaces the
output directory for that batch instead of appending duplicate records.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import uuid4

from trn000_config import (
    CODE_VERSION,
    HANDOVER_CHECKPOINT,
    LOG_DIR,
    OUTPUT_DIR,
    PROCESSING_ORDER,
    RULES_VERSION,
    HandoverError,
    append_event,
    approved_reference_keys,
    default_input_dir,
    iso_timestamp,
    previous_month,
    read_handover,
    utc_now,
    write_json,
)
from trn001_profile import profile
from trn002_clean import clean
from trn003_standardize import standardize
from trn004_transform import transform
from trn005_validate import validate
from trn006_package import package

EXIT_CODES = {
    "APPROVED": 0,
    "MANUAL REVIEW": 1,
    "REJECTED": 2,
}


def _read_checkpoint() -> dict:
    path = Path(HANDOVER_CHECKPOINT)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _parent_suffix(parent_run_id: str) -> str:
    suffix = parent_run_id.rsplit("_", 1)[-1]
    return suffix or uuid4().hex[:8]


def build_context(input_dir: Path, run_date: date | None = None,
                  parent_run_id: str | None = None,
                  batch_window: str | None = None,
                  handover: dict | None = None) -> dict:
    """Resolve the actual extraction run ID and batch window from the handover."""
    checkpoint = _read_checkpoint()
    handover_metadata = (handover or {}).get("metadata") or {}
    resolved_parent = (
        parent_run_id
        or handover_metadata.get("pipeline_run_id")
        or checkpoint.get("run_id")
    )
    if not resolved_parent:
        raise HandoverError(
            "HANDOVER_METADATA_MISSING",
            "No extraction run ID found in the handover. Provide --parent-run-id "
            "or restore the extraction checkpoint.",
        )

    last_extraction = (
        handover_metadata.get("extraction_end_timestamp")
        or checkpoint.get("last_successful_extraction")
    )
    if last_extraction:
        try:
            batch_end = date.fromisoformat(str(last_extraction)[:10])
        except ValueError:
            batch_end = run_date or date.today()
    else:
        batch_end = run_date or date.today()

    if batch_window:
        window = batch_window
        window_source = "cli"
    elif handover_metadata.get("batch_window"):
        window = str(handover_metadata["batch_window"])
        window_source = "handover"
    elif checkpoint.get("batch_window"):
        window = str(checkpoint["batch_window"])
        window_source = "checkpoint"
    else:
        window_start = checkpoint.get("window_start") or previous_month(batch_end).isoformat()
        window_end = checkpoint.get("window_end") or batch_end.isoformat()
        window = f"{window_start} to {window_end}"
        window_source = "derived_from_checkpoint"

    started = utc_now()
    run_day = run_date or started.date()
    suffix = _parent_suffix(str(resolved_parent))

    return {
        "input_dir": str(input_dir),
        "parent_run_id": str(resolved_parent),
        "batch_id": f"BATCH_{suffix}",
        "run_id": f"CITICARE_TRANS_{run_day:%Y%m%d}_{suffix}",
        "run_date": run_day.isoformat(),
        "batch_end": batch_end.isoformat(),
        "batch_window": window,
        "batch_window_source": window_source,
        "start_timestamp": iso_timestamp(started),
    }


def _failure_record(context: dict | None, started: float, exc: Exception) -> dict:
    """Build a Section 8.1 FAILED metadata record for an execution error."""
    code = exc.code if isinstance(exc, HandoverError) else "PROCESSING_ERROR"
    return {
        "run_id": (context or {}).get("run_id", f"CITICARE_TRANS_FAILED_{uuid4().hex[:8]}"),
        "parent_run_id": (context or {}).get("parent_run_id"),
        "batch_id": (context or {}).get("batch_id"),
        "batch_window": (context or {}).get("batch_window"),
        "file_name": "ALL",
        "start_timestamp": (context or {}).get("start_timestamp"),
        "end_timestamp": iso_timestamp(utc_now()),
        "status": "FAILED",
        "records_read": (context or {}).get("records_read"),
        "records_output": None,
        "records_rejected": None,
        "records_modified": None,
        "rules_applied": None,
        "validation_results": None,
        "error_code": code,
        "error_message": str(exc),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "code_version": CODE_VERSION,
        "rules_version": RULES_VERSION,
    }


def _write_failure(context: dict | None, started: float, exc: Exception) -> dict:
    record = _failure_record(context, started, exc)
    year = (record.get("end_timestamp") or "0000")[:4]
    write_json(
        Path(LOG_DIR) / "audit" / year / f"FAILED_{record['run_id']}.json",
        record,
    )
    append_event(
        Path(LOG_DIR) / "transform.log", "ERROR", record["run_id"], "transform",
        "batch_failed",
        {
            "parent_run_id": record["parent_run_id"],
            "batch_id": record["batch_id"],
            "error_code": record["error_code"],
            "error_message": record["error_message"],
            "duration_seconds": record["duration_seconds"],
        },
    )
    return record


def run(input_dir: Path | None = None, run_date: date | None = None,
        parent_run_id: str | None = None,
        batch_window: str | None = None) -> dict:
    """Execute one transformation batch and return its results."""
    started = time.perf_counter()
    context: dict | None = None

    try:
        input_dir = Path(input_dir) if input_dir is not None else default_input_dir()
        handover = read_handover(input_dir)
        context = build_context(
            input_dir, run_date=run_date, parent_run_id=parent_run_id,
            batch_window=batch_window, handover=handover,
        )

        records = handover["records"]
        schema = handover["schema"]
        reference = handover["reference"]
        context["records_read"] = {
            name: len(records[name]) for name in PROCESSING_ORDER
        }
        context["reference_counts"] = {
            name: len(approved_reference_keys(reference, name))
            for name in ("puroks", "residents")
        }

        prof = profile(records, schema, context)
        write_json(
            Path(LOG_DIR) / "profile" / f"profile_{context['batch_id']}.json", prof
        )

        cleaned = clean(records, context, reference)
        standardized = standardize(cleaned["records"], context)

        rejected = Counter(cleaned["rejected"]) + Counter(standardized["rejected"])
        duplicates = Counter(cleaned["duplicates"])
        excluded = sum(rejected.values()) + sum(duplicates.values())

        transformed = transform(
            standardized["records"], context, excluded, reference
        )
        rules = (
            Counter(cleaned["rules"])
            + Counter(standardized["rules"])
            + Counter(transformed["rules"])
        )

        metrics = {
            "records_read": context["records_read"],
            "rejected": rejected,
            "duplicates": duplicates,
            "modified": standardized["modified"],
            "excluded": excluded,
        }
        validation = validate(
            transformed["tables"], metrics, context,
            transformed["join_cardinality"], schema, reference,
        )

        context["records_rejected"] = {name: rejected[name] for name in PROCESSING_ORDER}
        context["records_modified"] = {
            name: standardized["modified"][name] for name in PROCESSING_ORDER
        }
        context["duration_seconds"] = round(time.perf_counter() - started, 3)
        context["end_timestamp"] = iso_timestamp(utc_now())
        context["error_code"] = None
        context["error_message"] = None

        quarantine = cleaned["quarantine"] + standardized["quarantine"]
        manifest = package(
            context,
            transformed["tables"],
            validation,
            prof,
            rules,
            quarantine,
            transformed["business_rules"],
            transformed["join_cardinality"],
        )

        return {
            "context": context,
            "profile": prof,
            "validation": validation,
            "manifest": manifest,
            "rules": rules,
            "quarantine": quarantine,
        }
    except Exception as exc:
        _write_failure(context, started, exc)
        raise


def approve(batch_id: str, reviewer: str) -> int:
    """Record authorized manual approval for a MANUAL REVIEW batch (Section 10.2)."""
    target = Path(OUTPUT_DIR) / batch_id
    manifest_path = target / "manifest.json"
    metadata_path = target / "metadata.json"
    if not manifest_path.is_file():
        print(f"No published batch found for {batch_id}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("decision") != "MANUAL REVIEW":
        print(f"Batch {batch_id} is {manifest.get('decision')}; nothing to approve.")
        return 1

    manifest["handover_status"] = "APPROVED"
    manifest["reviewed_by"] = reviewer
    manifest["reviewed_at"] = iso_timestamp(utc_now())
    write_json(manifest_path, manifest)

    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["handover_status"] = "APPROVED"
        metadata["reviewed_by"] = reviewer
        metadata["reviewed_at"] = manifest["reviewed_at"]
        write_json(metadata_path, metadata)

    validation_path = target / "validation_report.json"
    if validation_path.is_file():
        report = json.loads(validation_path.read_text(encoding="utf-8"))
        report["handover_status"] = "APPROVED"
        report["reviewed_by"] = reviewer
        report["reviewed_at"] = manifest["reviewed_at"]
        write_json(validation_path, report)

    append_event(
        Path(LOG_DIR) / "handover.log", "INFO", manifest.get("run_id"), "handover",
        "manual_approval",
        {
            "batch_id": batch_id,
            "decision": "MANUAL REVIEW",
            "handover_status": "APPROVED",
            "reviewer": reviewer,
        },
    )
    print(f"Batch {batch_id} approved by {reviewer}.")
    return 0


def print_summary(result: dict) -> None:
    context = result["context"]
    validation = result["validation"]
    metadata = result["manifest"]

    print("\nCitiCare Stage 2 - Data Transformation")
    print(f"batch_id           {context['batch_id']}")
    print(f"run_id             {context['run_id']}")
    print(f"parent_run_id      {context['parent_run_id']}")
    print(f"batch_window       {context['batch_window']} ({context['batch_window_source']})")
    print(f"code_version       {CODE_VERSION}")
    print(f"rules_version      {RULES_VERSION}")

    print("\nOutput files")
    for name in PROCESSING_ORDER:
        print(f"  {metadata['files'][name]['file_name']:<34} {metadata['files'][name]['rows']}")

    print("\nValidation")
    for check in validation["checks"]:
        print(f"  {check['id']:<5} {check['status']:<8} {check['name']}")

    print(f"\nOverall            {validation['status']}")
    print(f"Decision           {validation['decision']}")
    print(f"Handover           {validation['handover_status']}")

    print("\nRecord counts")
    for name in PROCESSING_ORDER:
        print(
            f"  {name:<34} read={context['records_read'][name]:<4} "
            f"output={metadata['counts']['records_output'][name]:<4} "
            f"rejected={context['records_rejected'][name]:<4} "
            f"modified={context['records_modified'][name]}"
        )
    print(
        f"  duplicate exclusions              "
        f"{sum(metadata['counts']['records_duplicates_excluded'].values())}"
    )
    print(f"  rejection rate                    "
          f"{validation['metrics']['overall_rejection_rate']:.2%}")
    print(
        f"  approved reference parents        "
        f"puroks={context['reference_counts']['puroks']} "
        f"residents={context['reference_counts']['residents']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CitiCare Stage 2 transformation")
    parser.add_argument("--input-dir", default=None,
                        help="Approved Stage 1 handover directory (default: "
                             "Extraction/data/handover; legacy fallback: "
                             "Extraction/data/input)")
    parser.add_argument("--run-date", default=None,
                        help="Override the run date (YYYY-MM-DD) for a reproducible batch")
    parser.add_argument("--parent-run-id", default=None,
                        help="Override the extraction run ID recorded in the handover")
    parser.add_argument("--batch-window", default=None,
                        help="Override the monthly extraction window recorded in the handover")
    parser.add_argument("--approve", metavar="BATCH_ID", default=None,
                        help="Record authorized manual approval for a held batch")
    parser.add_argument("--reviewer", default=None, help="Reviewer name for --approve")
    args = parser.parse_args(argv)

    if args.approve:
        if not args.reviewer:
            print("--reviewer is required with --approve")
            return 1
        return approve(args.approve, args.reviewer)

    run_date = date.fromisoformat(args.run_date) if args.run_date else None
    try:
        result = run(
            Path(args.input_dir) if args.input_dir else None,
            run_date=run_date,
            parent_run_id=args.parent_run_id,
            batch_window=args.batch_window,
        )
    except Exception as exc:  # FAILED: preserve inputs and logs, correct, rerun.
        code = exc.code if isinstance(exc, HandoverError) else "PROCESSING_ERROR"
        print(f"Transformation FAILED [{code}]: {exc}")
        return 3

    print_summary(result)
    return EXIT_CODES.get(result["validation"]["decision"], 3)


if __name__ == "__main__":
    sys.exit(main())
