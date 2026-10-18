"""EXT-002: retain records newer than the previous successful extraction."""

from datetime import datetime, timezone
import json
from pathlib import Path

from ext001_extract import TIMESTAMP_COLUMNS


def parse_timestamp(value):
    if not value:
        return None
    value = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def filter_incremental(records, checkpoint_file):
    checkpoint = Path(checkpoint_file)
    previous_value = None
    if checkpoint.exists():
        previous_value = json.loads(checkpoint.read_text(encoding="utf-8")).get("last_successful_extraction")
    previous = parse_timestamp(previous_value)
    warnings = []
    if previous is None:
        return records, warnings

    result = {}
    for dataset, rows in records.items():
        column = next((name for name in TIMESTAMP_COLUMNS[dataset] if rows and name in rows[0]), None)
        if not column:
            result[dataset] = rows
            warnings.append(f"{dataset}: no supported timestamp column; full dataset retained")
            continue
        selected = []
        invalid = 0
        for row in rows:
            timestamp = parse_timestamp(row.get(column))
            if timestamp is None:
                invalid += 1
            elif timestamp > previous:
                selected.append(row)
        if invalid:
            warnings.append(f"{dataset}: {invalid} rows have invalid {column} timestamps")
        result[dataset] = selected
    return result, warnings


def save_checkpoint(checkpoint_file, timestamp, run_id):
    path = Path(checkpoint_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_successful_extraction": timestamp, "run_id": run_id}, indent=2), encoding="utf-8")
