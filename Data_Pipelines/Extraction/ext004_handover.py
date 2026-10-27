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
    """Write the approved incremental handover atomically.

    Only an APPROVED extraction publishes CSV files. A held or rejected run
    invalidates the status marker while preserving any previous approved files
    for audit and recovery; Stage 2 checks the marker and refuses to consume
    them.
    """
    handover_dir = Path(handover_dir)
    approved = status == "APPROVED"
    records = records or {}
    incremental = incremental or {}
    handover_counts = {
        name: len(incremental.get(name, [])) if approved else 0
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

    if not approved:
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


def _append_process_logs(log_dir, metadata):
    """Append standard line-oriented records to each process .log file."""
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
            "extraction_type": "Batch Extraction",
            "extraction_tool": "Python",
            "extraction_schedule": "Monthly",
            "records_read": metadata["records_read"].get(dataset, 0),
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
    metadata = {
        "pipeline_run_id": run_id,
        "files": [f"{name}.csv" for name in records_read],
        "extraction_start_timestamp": started_at,
        "extraction_end_timestamp": ended_at.isoformat(),
        "extraction_status": status,
        "handover_status": _handover_status(status),
        "records_read": records_read,
        "records_extracted": records_extracted or {
            name: 0 for name in records_read
        },
        "records_rejected": records_rejected or {name: 0 for name in records_read},
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
    _append_process_logs(log_dir, metadata)
    return str(handover_path), run_id, metadata
