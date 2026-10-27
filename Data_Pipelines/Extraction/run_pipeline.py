"""Run EXT-001 through EXT-004 with terminal-only results."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ext001_extract import (
    CHECKPOINT_FILE,
    HANDOVER_DIR,
    INPUT_DIR,
    export_from_postgresql,
    read_csv_datasets,
)
from ext002_incremental import filter_incremental, save_checkpoint
from ext003_validate import validate
from ext004_handover import acceptance, write_result

EXIT_CODES = {
    "APPROVED": 0,
    "MANUAL REVIEW": 1,
    "REJECTED": 2,
    "FAILED": 3,
}


def terminal_summary(result):
    metadata = result.get("metadata", {})
    validation = metadata.get("validation_results", {})
    return {
        "status": result.get("status"),
        "pipeline_run_id": metadata.get("pipeline_run_id"),
        "files": metadata.get("files", []),
        "records_read": metadata.get("records_read", {}),
        "records_extracted": metadata.get("records_extracted", {}),
        "records_rejected": metadata.get("records_rejected", {}),
        "extraction_window": metadata.get("extraction_window", {}),
        "validation_status": validation.get("status"),
        "validation_errors": validation.get("errors", []),
        "validation_warnings": validation.get("warnings", []),
        "error_message": metadata.get("error_message"),
        "extraction_duration_seconds": metadata.get("extraction_duration_seconds"),
        "handover": result.get("handover"),
        "log_directory": "logs",
    }


def print_terminal_summary(summary):
    sections = {
        "Extraction Summary": [
            "status", "pipeline_run_id", "files", "extraction_window",
        ],
        "Record Counts": [
            "records_read", "records_extracted", "records_rejected",
        ],
        "Validation Summary": [
            "validation_status", "validation_errors", "validation_warnings",
        ],
        "Handover Summary": [
            "error_message", "extraction_duration_seconds", "handover", "log_directory",
        ],
    }

    def rows_for(field, value):
        if isinstance(value, dict):
            return [(f"{field} - {key}", item) for key, item in value.items()] \
                or [(field, "None")]
        if isinstance(value, list):
            return [(field, item) for item in value] or [(field, "None")]
        return [(field, value if value not in (None, "") else "None")]

    for section, fields in sections.items():
        rows = []
        for field in fields:
            rows.extend(rows_for(field, summary.get(field)))
        if not rows:
            rows = [(section, "None")]
        width = max(len(field) for field, _ in rows)
        print(f"\n{section}")
        print("Field".ljust(width) + "  Value")
        for field, value in rows:
            print(str(field).ljust(width) + f"  {value}")


def run(input_dir=INPUT_DIR, handover_dir=HANDOVER_DIR,
        checkpoint_file=CHECKPOINT_FILE, export_source=True,
        full_load=False):
    """Extract, validate, and publish the approved handover.

    The handover contains only the incremental records selected by the previous
    successful extraction boundary. ``full_load`` deliberately ignores that
    boundary for an initial load or a controlled full reload.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    records = {}
    try:
        if export_source:
            export_from_postgresql(
                os.getenv("CITICARE_DATABASE_URL")
                or os.getenv("SUPABASE_DB_URL")
                or os.getenv("DATABASE_URL"),
                input_dir,
            )
        records = read_csv_datasets(input_dir)
        records_read = {name: len(rows) for name, rows in records.items()}
        validation = validate(records)
        if full_load:
            incremental, warnings = records, []
        else:
            incremental, warnings = filter_incremental(records, checkpoint_file)
        status = acceptance(validation, warnings)
        records_extracted = {name: len(rows) for name, rows in incremental.items()}
        previous = None
        if Path(checkpoint_file).exists():
            previous = json.loads(
                Path(checkpoint_file).read_text(encoding="utf-8")
            ).get("last_successful_extraction")
        extraction_window = {
            "previous_successful_extraction": previous,
            "current_extraction": started_at,
            "full_load": full_load,
        }
        path, run_id, metadata = write_result(
            handover_dir, status, records_read, records_extracted, validation,
            started_at, extraction_window,
            records_rejected={name: 0 for name in records_read},
            records=records, incremental=incremental, input_dir=input_dir,
        )
        if status == "APPROVED":
            save_checkpoint(checkpoint_file, metadata["extraction_end_timestamp"], run_id)
        return {"status": status, "handover": str(path), "metadata": metadata}
    except (FileNotFoundError, ValueError) as error:
        records_read = {name: len(rows) for name, rows in records.items()}
        path, _, metadata = write_result(
            handover_dir, "REJECTED", records_read, {},
            {"status": "FAIL", "checks": [], "errors": [str(error)], "warnings": []},
            started_at, {"previous_successful_extraction": None,
                         "current_extraction": started_at, "full_load": full_load},
            str(error), records=records, incremental={}, input_dir=input_dir,
        )
        return {"status": "REJECTED", "handover": str(path), "metadata": metadata}
    except Exception as error:
        records_read = {name: len(rows) for name, rows in records.items()}
        path, _, metadata = write_result(
            handover_dir, "FAILED", records_read, {},
            {"status": "FAIL", "checks": [], "errors": [str(error)], "warnings": []},
            started_at, {"previous_successful_extraction": None,
                         "current_extraction": started_at, "full_load": full_load},
            str(error), records=records, incremental={}, input_dir=input_dir,
        )
        return {"status": "FAILED", "handover": str(path), "metadata": metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-export", action="store_true",
                        help="Use existing CSV files instead of exporting from PostgreSQL")
    parser.add_argument("--full", action="store_true",
                        help="Ignore the previous extraction boundary and hand over all validated records")
    parser.add_argument("--handover-dir", default=str(HANDOVER_DIR),
                        help="Approved handover directory (default: data/handover)")
    parser.add_argument("--checkpoint-file", default=str(CHECKPOINT_FILE),
                        help="Extraction boundary file (default: data/checkpoint.json)")
    args = parser.parse_args()
    result = run(
        handover_dir=Path(args.handover_dir),
        checkpoint_file=Path(args.checkpoint_file),
        export_source=not args.no_export,
        full_load=args.full,
    )
    print_terminal_summary(terminal_summary(result))
    sys.exit(EXIT_CODES.get(result.get("status"), 3))
