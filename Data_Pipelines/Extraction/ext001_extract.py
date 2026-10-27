"""EXT-001: configure CitiCare PostgreSQL and extract required CSV datasets."""

import csv
import os
from pathlib import Path

DATASETS = {
    "residents": ("resident_id", ["resident_id", "purok_id", "risk_level"]),
    "resident_chronic_conditions": ("condition_id", ["condition_id", "resident_id", "condition_name", "created_at"]),
    "schedules": ("schedule_id", ["schedule_id", "resident_id", "date", "status"]),
    "puroks": ("purok_id", ["purok_id", "name"]),
}

TIMESTAMP_COLUMNS = {
    "residents": ("updated_at", "created_at"),
    "resident_chronic_conditions": ("updated_at", "created_at"),
    "schedules": ("updated_at", "created_at", "date"),
    "puroks": ("updated_at", "created_at"),
}


def _load_dotenv():
    """Load simple KEY=VALUE settings without requiring python-dotenv."""
    env_file = Path(__file__).with_name(".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DATA_DIR = Path(__file__).resolve().parent / "data"
INPUT_DIR = Path(os.getenv("CITICARE_INPUT_DIR", str(DATA_DIR / "input")))
HANDOVER_DIR = Path(os.getenv("CITICARE_HANDOVER_DIR", str(DATA_DIR / "handover")))
CHECKPOINT_FILE = Path(
    os.getenv("CITICARE_CHECKPOINT_FILE", str(DATA_DIR / "checkpoint.json"))
)


def read_csv_datasets(input_dir=INPUT_DIR):
    input_dir = Path(input_dir)
    missing_files = [
        str(input_dir / f"{dataset}.csv")
        for dataset in DATASETS
        if not (input_dir / f"{dataset}.csv").is_file()
    ]
    if missing_files:
        raise FileNotFoundError(
            "Missing required CitiCare CSV files:\n- " + "\n- ".join(missing_files)
        )
    records = {}
    for dataset, (_, required) in DATASETS.items():
        path = Path(input_dir) / f"{dataset}.csv"
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            missing = set(required) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{dataset}: missing columns {sorted(missing)}")
            records[dataset] = list(reader)
    return records


def export_from_postgresql(database_url=None, output_dir=INPUT_DIR):
    """Export the six source tables. Requires psycopg[binary]."""
    database_url = (
        database_url
        or os.getenv("CITICARE_DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("DATABASE_URL")
    )
    if not database_url:
        if os.getenv("SUPABASE_URL"):
            raise RuntimeError(
                "SUPABASE_URL is an API URL. Set SUPABASE_DB_URL to the PostgreSQL "
                "connection string from Supabase Dashboard > Connect > PostgreSQL"
            )
        raise RuntimeError("Set CITICARE_DATABASE_URL, SUPABASE_DB_URL, or DATABASE_URL before automatic export")
    import psycopg

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(database_url) as connection:
        for table, (_, columns) in DATASETS.items():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s",
                    (table,),
                )
                available = {row[0] for row in cursor.fetchall()}
                missing = set(columns) - available
                if missing:
                    raise ValueError(f"{table}: source columns missing {sorted(missing)}")
                optional_timestamps = [
                    name for name in TIMESTAMP_COLUMNS[table]
                    if name in available and name not in columns
                ]
                export_columns = list(columns) + optional_timestamps
                where_clause = " WHERE resident_id IS NOT NULL" if table == "schedules" else ""
                cursor.execute(f"SELECT {', '.join(export_columns)} FROM {table}{where_clause}")
                rows = cursor.fetchall()
            with (output_dir / f"{table}.csv").open("w", newline="", encoding="utf-8") as target:
                writer = csv.writer(target)
                writer.writerow(export_columns)
                writer.writerows(rows)
