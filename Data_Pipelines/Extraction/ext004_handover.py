"""EXT-004: acceptance decision, extraction metadata, logs, and handover."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def acceptance(validation, warnings):
    if validation.get("errors"):
        return "REJECTED"
    if warnings or validation.get("warnings"):
        return "MANUAL REVIEW"
    return "APPROVED"


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
        "handover_decision": "TERMINAL_OUTPUT" if status == "APPROVED" else "HELD",
        "error_message_code": metadata["error_message"] or "NULL",
        **common,
    })



def write_result(output_dir, status, records_read, records_extracted, validation,
                 started_at, extraction_window, error_message=None, records_rejected=None):
    """Create terminal output and retain Stage 1 operational and audit logs."""
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
        "records_read": records_read,
        "records_extracted": records_extracted,
        "records_rejected": records_rejected or {name: 0 for name in records_read},
        "extraction_window": extraction_window,
        "validation_results": validation,
        "error_message": error_message,
        "extraction_duration_seconds": duration_seconds,
    }
    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    _append_process_logs(log_dir, metadata)
    return "TERMINAL_OUTPUT", run_id, metadata
