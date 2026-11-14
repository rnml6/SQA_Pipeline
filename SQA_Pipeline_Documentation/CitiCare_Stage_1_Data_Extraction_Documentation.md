# Stage 1: Data Extraction Documentation

## CitiCare Health Data Analytics Pipeline

### Objective

The objective of the extraction stage is to retrieve health data from the **CitiCare** source system and prepare a documented and validated dataset for the succeeding **Transformation Stage**.

The CitiCare pipeline processes resident and health information, including **resident profiles, chronic conditions, consultation schedules, and purok information**. PostgreSQL serves as the primary source database, while Python processes the exported health datasets for batch processing.

---

# 1. Data Source and Extraction Specifications

## 1.1 Source System

### CitiCare: Barangay Gumamela Healthcare Monitoring System

The CitiCare system collects and manages resident health information recorded by Barangay Health Workers (BHWs). Health records are stored in the database and used for monitoring, reporting, analytics, risk classification, and decision-support functions.

The source records include:

- Resident medical profile
- Chronic conditions
- Consultation schedules
- Purok information

---

## 1.2 Source Database or File

**Database Management System:** PostgreSQL  
**Source Database:** CitiCare PostgreSQL Database  
**File Format:** CSV

The CitiCare system uses PostgreSQL as the primary database for storing resident and health-related records. For the ETL pipeline, the required records are exported from the PostgreSQL database into CSV files. These exported CSV files serve as the source files read by Python during the extraction stage before the data undergoes extraction validation and transformation. This follows the existing CitiCare pipeline where resident profiles and health records originate from the CitiCare database and exported datasets are processed using Python

---

## 1.3 Extraction Method

| Item | Specification |
|---|---|
| Extraction type | **Incremental batch extraction**. The first run is a full load; later runs extract only records added or changed since the last successful run. |
| Extraction tool | **Python 3** — `csv`, `json`, `pathlib`, and `datetime` for file handling and window filtering; `psycopg` for the PostgreSQL export. |
| Source connection | PostgreSQL connection string supplied through `CITICARE_DATABASE_URL`, `SUPABASE_DB_URL`, or `DATABASE_URL`. |
| Output format | CSV — `residents.csv`, `resident_chronic_conditions.csv`, `schedules.csv`, `puroks.csv`. |
| Full-load mode | Used only for the initial load or a controlled full refresh (`--full`). |

The selected records are extracted from PostgreSQL using SQL queries executed through Python and exported into CSV files. These CSV files serve as the input datasets for the succeeding transformation stage, where Python processes, cleans, validates, and transforms the data. This is consistent with the existing CitiCare ETL design in which Python reads exported datasets before loading processed information into SQLite.

### Extraction Process

```text
CitiCare PostgreSQL Database
            |
            v
      Exported CSV Data
            |
            v
     Python Extraction
            |
            v
     Raw Extracted Data
            |
            v
   Extraction Validation
            |
            v
    Transformation Stage
```

### Extraction Schedule

The extraction is performed **monthly**. At the end of each month, the pipeline extracts only the records added or updated during that extraction period. This monthly schedule is consistent with the pipeline schedule already defined in the CitiCare documentation.

### Incremental Extraction

CitiCare uses an **incremental extraction** method to retrieve newly added or updated health records from the PostgreSQL database. Instead of extracting the entire database during every pipeline run, only records that have been created or modified since the previous successful extraction are selected.

The pipeline stores the timestamp of the last successful extraction in the checkpoint file `data/checkpoint.json`, using the field `last_successful_extraction` (UTC, ISO-8601). On each run, a row is selected when its window field is **later than** that recorded boundary.

| Dataset | Window field (evaluated in order) | Window logic |
|---|---|---|
| `residents` | `updated_at`, otherwise `created_at` | Select rows whose window value is later than the checkpoint |
| `resident_chronic_conditions` | `updated_at`, otherwise `created_at` | Select rows whose window value is later than the checkpoint |
| `schedules` | `updated_at`, otherwise `created_at`, otherwise `date` | Select rows whose window value is later than the checkpoint; `date` is a fallback only |
| `puroks` | `updated_at`, otherwise `created_at` | Select rows whose window value is later than the checkpoint |

**Window boundary rules**

- The comparison is strict (`window value > last_successful_extraction`), so a record exactly on the boundary is not extracted twice.
- All values are normalized to UTC before comparison; date-only values are treated as midnight UTC.
- If the checkpoint is missing or empty, the run performs a full load.
- The checkpoint is updated to the run's extraction end timestamp **only when the run is `APPROVED`**, so a rejected or failed run is retried over the same window.
- If a dataset has no supported timestamp column, the full dataset is retained and a `WARNING` is logged; the run then requires manual review instead of silently accepting the data.
- Rows whose window value cannot be parsed are excluded, counted, and reported in the extraction log.
- Late-arriving rows with timestamps older than the boundary are not captured automatically; they require a documented backfill or a controlled full reload.

---

## 1.4 Extraction Scope

The extraction includes the resident and health information required by the CitiCare data pipeline.

| Source Table / Data | Extraction Purpose |
|---|---|
| `residents` | Retrieve resident information required for resident and purok-level health analysis |
| `resident_chronic_conditions` | Retrieve chronic conditions recorded for residents |
| `schedules` | Retrieve consultation schedules and their completion or missed status |
| `puroks` | Retrieve purok information for barangay-level grouping and analysis |

The extraction covers the records available in the exported CitiCare datasets during the scheduled monthly batch run.

---

## 1.5 Source Limitations and Assumptions

The following limitations and assumptions apply:

- Required health records must be available in the CitiCare database before extraction begins.
- Required source tables and columns must exist.
- Exported CSV datasets must be available and accessible to the Python extraction process.
- Source tables should provide an `updated_at` or `created_at` timestamp for incremental filtering. A dataset without a window column is extracted in full and flagged for manual review.
- The checkpoint file `data/checkpoint.json` must be readable. If it is missing, the run executes a full load.
- Missing or incomplete source records may affect the extracted dataset.
- Unexpected database schema changes may cause extraction validation to fail.
- Missing or corrupted CSV files may interrupt an extraction run.

---

# 2. Source Tables and Column Specification

## 2.1 `residents`

### Purpose

The `residents` table contains information required to identify residents, associate them with their puroks, and support resident risk analysis.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `resident_id` | BIGINT | Primary Key | Unique identifier of the resident |
| `purok_id` | BIGINT | Foreign Key → `puroks(purok_id)` | Identifies the purok where the resident belongs |
| `risk_level` | TEXT | — | Indicates the resident's health risk level |
| `created_at` | TIMESTAMP | Extraction window column | Indicates when the resident record was created; used as the incremental window field when `updated_at` is unavailable |

**Reason for inclusion:** Resident information is required to identify residents and support risk classification and purok-level health analysis. The window timestamp is included because the monthly incremental extraction cannot select changed records without it.

> `updated_at` is also exported when the source table provides it and takes priority over `created_at` during incremental filtering. Window columns are used only to select records; they are not required transformation inputs.

---

## 2.2 `resident_chronic_conditions`

### Purpose

The `resident_chronic_conditions` table contains chronic conditions recorded for residents.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `condition_id` | BIGINT | Primary Key | Unique identifier of the chronic condition record |
| `resident_id` | BIGINT | Foreign Key → `residents(resident_id)` | Identifies the resident who has the condition |
| `condition_name` | TEXT | — | Name of the chronic condition |
| `created_at` | TIMESTAMP | Extraction window column | Indicates when the condition was recorded; used as the incremental window field |
| `updated_at` | TIMESTAMP | Extraction window column (when present) | Indicates the last change to the record; preferred over `created_at` for incremental filtering |

**Reason for inclusion:** Chronic condition records are required for disease prevalence and resident health analysis. The window timestamp allows only newly recorded or modified conditions to be re-extracted each month.

---

## 2.3 `schedules`

### Purpose

The `schedules` table contains scheduled consultations associated with residents.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `schedule_id` | BIGINT | Primary Key | Unique identifier of the schedule |
| `resident_id` | BIGINT | Foreign Key → `residents(resident_id)` | Identifies the resident associated with the schedule |
| `date` | DATE | — | Indicates when the consultation is scheduled |
| `status` | TEXT | — | Indicates whether the schedule was completed or missed |
| `updated_at` | TIMESTAMP | Extraction window column (when present) | Indicates the last change to the schedule; preferred over `created_at` for incremental filtering |
| `created_at` | TIMESTAMP | Extraction window column | Indicates when the schedule record was created |

**Reason for inclusion:** Schedule records are required to identify and analyze missed health consultations. The window timestamps allow newly created or updated schedules to be captured each month.

---

## 2.4 `puroks`

### Purpose

The `puroks` table contains the purok information used to organize residents geographically within the barangay.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `purok_id` | BIGINT | Primary Key | Unique identifier of the purok |
| `name` | TEXT | — | Name of the purok |
| `created_at` | TIMESTAMP | Extraction window column | Indicates when the purok record was created; used when `updated_at` is unavailable |

**Reason for inclusion:** Purok information is required to group resident health information and support purok-level prioritization and analysis. The window timestamp is required when purok records are added or renamed.

---

## 2.5 Source Relationships

| Relationship | Description |
|---|---|
| `puroks` → `residents` | One purok can contain many residents through `residents.purok_id`. |
| `residents` → `resident_chronic_conditions` | One resident can have many chronic condition records through `resident_chronic_conditions.resident_id`. |
| `residents` → `schedules` | One resident can have many schedules through `schedules.resident_id`. |

---

# 3. Extraction Validation and Data Quality Checks

The extraction stage focuses on verifying that the required health data was successfully obtained from the source datasets. Data cleaning, standardization, health classification, and other transformations are handled in the succeeding stages of the pipeline.


| Check Name | Target | Purpose | Severity | PASS Criteria | FAIL Criteria |
|---|---|---|---|---|---|
| Source Connectivity | PostgreSQL source and credentials | Confirm the pipeline can reach and read the source | Critical | Connection is established within 30 seconds and a test `SELECT` returns a result | Connection, authentication, or query fails, or the connection times out |
| Source File Availability | Exported CSV datasets | Verify that all source datasets are available and readable | Critical | 4 of 4 required CSV files exist in the input directory and each opens as UTF-8 with a readable header | Any required file is missing, locked, or unreadable |
| Required Datasets | All required source data | Ensure every required dataset is loaded | Critical | 4 of 4 datasets are loaded successfully | One or more required datasets are absent |
| Required Columns | Selected columns per dataset | Ensure every required field exists | Critical | 0 missing required columns in each dataset | 1 or more required columns are missing |
| Column Naming Convention | All extracted column names | Detect inconsistent or unexpected naming | Non-critical | 100% of column names match `^[a-z][a-z0-9]*(_[a-z0-9]+)*$` | 1 or more column names do not match the convention |
| Identifier Presence | Primary and foreign keys | Ensure records can be identified and related | Critical | 0 blank primary-key values and 0 blank required foreign-key values | 1 or more required identifiers are blank |
| Primary Key Uniqueness | Primary key columns | Detect duplicate identifiers | Critical | 0 duplicate primary-key values per dataset | 1 or more duplicate primary keys are found |
| Data Type Conformity | Column values | Verify values match the documented data type | Critical | 0 values fail the documented type for their column | 1 or more values have an invalid type |
| Record Count Reconciliation | Extracted datasets | Verify extraction completeness | Critical | For every dataset, `records extracted + records rejected = records read`, and `records read` equals the number of data rows in the CSV | The counts do not reconcile for any dataset |
| Foreign Key Availability | Relationship columns | Verify relationships can be maintained | Critical | 0 extracted `resident_id` or `purok_id` values are absent from the referenced dataset | 1 or more foreign-key values have no matching parent record |
| Incremental Window Conformity | Extracted records | Confirm only in-window records were extracted | Critical | 0 extracted records have a window value earlier than or equal to the checkpoint | 1 or more extracted records fall outside the declared window |
| Extraction Completion | Extraction process | Detect failures or interruptions | Critical | All 4 datasets are processed and a valid end timestamp is recorded | An unhandled exception occurs or the end timestamp is missing |
| Extraction Status | Pipeline run | Determine the overall result of extraction | Critical | Status is recorded as `APPROVED`, `MANUAL REVIEW`, `REJECTED`, or `FAILED` | No status is recorded |

A **Critical** check that fails blocks handover. A **Non-critical** check that fails produces a `WARNING`, which routes the run to manual review. The overall extraction status is `APPROVED` only when every critical check passes and no warning is open.

Source Connectivity is executed before export with a 30-second connection timeout and a test `SELECT`. A failure records the `Source Connectivity` check and `CONNECTION_ERROR` in the extraction log, sets the run to `FAILED`, and stops the handover.

---
# 4. Extraction Metadata and Log Specification


The CitiCare extraction process records metadata and logs for every extraction run. These records provide information about when the extraction occurred, which CSV files were processed, how many records were handled, whether validation was successful, and whether any errors occurred.

| Metadata / Log Field | Purpose | Example Value / Format |
|---|---|---|
| Pipeline Run ID | Provides a unique identifier for each extraction run. | `CITICARE_EXT_20261114_3d209da2` |
| Table / File Name | Identifies the PostgreSQL table or exported CSV file being processed. | `residents.csv` |
| Extraction Start Timestamp | Records when Python started extracting data from the CSV file. | `2026-10-01 08:00:00` |
| Extraction End Timestamp | Records when the extraction process finished. | `2026-10-01 08:02:15` |
| Extraction Status | Indicates the overall result of the extraction. | `APPROVED`, `MANUAL REVIEW`, `REJECTED`, `FAILED` |
| Records Read | Records the total number of records read from the exported CSV file. | `350` |
| Records Extracted | Records the number of records successfully extracted and accepted as raw data. | `347` |
| Records Rejected | Records excluded from the handover because they fall outside the extraction window or fail an extraction check. | `3` |
| Extraction Window | Identifies the boundary and period covered by the incremental extraction. | `previous: 2026-10-01T00:00:00+00:00; current: 2026-11-01T00:00:00+00:00` |
| Validation Results | Records the result of the extraction validation checks. | `Passed` or `Failed: 3 missing resident_id values` |
| Error Message / Code | Records details of errors encountered during extraction. | `NULL` if successful; `CSV_READ_ERROR` if failed |
| Extraction Duration | Measures the total time required to complete the extraction. | `00:02:15` |

The **Pipeline Run ID** is used to identify and group CSV files processed during the same monthly extraction run. Each CSV file maintains its own log entry so that its record counts, validation results, and extraction status can be individually monitored.

`Records Rejected` is calculated as `Records Read − Records Extracted`, so the counts must reconcile in every log entry. `Validation Results` stores the outcome of each named check from Section 3, including the failing check name and detail, and the `Extraction Window` records both the previous successful boundary and the current run timestamp.

### Use of Extraction Metadata and Logs

The extraction metadata and logs are used for **monitoring, troubleshooting, auditing, and recovery**.

- **Monitoring** — Extraction status, timestamps, record counts, and duration are used to verify that the monthly extraction completed successfully.
- **Troubleshooting** — Validation results and error messages help identify missing files, invalid records, CSV reading errors, or interrupted extraction processes.
- **Auditing** — The pipeline run ID, extraction window, file names, and record counts provide a traceable history of the data processed during each monthly extraction.
- **Recovery** — Failed or partially completed extraction runs can be identified through their run ID and status. The affected CSV files can then be corrected and reprocessed before proceeding to the Transformation Stage.

# 5. Log Retention and Access

The CitiCare extraction logs are retained to provide a reliable history of pipeline activities and to support monitoring, troubleshooting, auditing, and recovery. Logs are managed to ensure that extraction records remain available when needed while preventing unnecessary long-term storage.

| Log Management Area | Specification | Justification |
|---|---|---|
| Log Retention Period | Extraction logs are retained for **12 months**. | Covers a full annual cycle of monthly runs, allowing month-to-month comparison, year-end auditing, and recovery of recent batches. |
| Storage Location | Extraction logs are stored in `Data_Pipelines/Extraction/logs/` (`extract.log`, `incremental.log`, `validate.log`, `handover.log`), with archived logs under `logs/archive/`. | Keeps operational evidence beside the extraction code and separates active from archived records. |
| Access Permissions | Read/write access is limited to **authorized developers or system administrators** responsible for the ETL pipeline; no public or shared read access is granted. | Extraction logs contain resident identifiers and health details, so access is restricted to protect personal health information. |
| Archiving Requirements | On the first run of a new month, the four active logs are moved automatically to `logs/archive/<year>/<name>-<year>-<month>.log` while still inside the 12-month retention period, and remain readable for auditing or recovery. The active log directory holds only the current month. | Preserves evidence without slowing normal troubleshooting on current logs. |
| Deletion Rules | Archived operational logs older than **365 days** are deleted automatically at the start of a run. Active logs are never deleted. A `.hold` file placed in `logs/archive/` suspends automatic deletion while an investigation is open. | Prevents loss of evidence during an open investigation and avoids retaining personal health data longer than necessary. |
| Responsible Process | Rotation, archiving, and retention are performed by the pipeline's log management process at the start of each run. An authorized system administrator or developer controls the `.hold` file and reviews the deletion events written to `handover.log`. | Assigns clear accountability for irreversible log actions. |

Each run records `logs_archived`, `logs_purged`, `log_retention_days`, and `log_retention_hold` in `handover.log`, so archival and deletion actions are auditable.

### Operational Logs and Audit Records

CitiCare distinguishes between **operational logs** and **audit records** when necessary.

- **Operational logs** contain information about individual extraction runs, including timestamps, processing status, record counts, validation results, duration, and extraction errors. These logs are primarily used for monitoring and troubleshooting and are retained for **12 months**.

- **Audit records** contain important historical information about extraction activities, such as pipeline run IDs, extraction windows, files processed, and final extraction results. If required for documentation or auditing purposes, these records may be retained for a longer period than regular operational logs.

### Log Protection and Deletion

Extraction logs **must not be deleted before the defined retention period**. Logs must also be preserved beyond the normal retention period when they are still required for an ongoing troubleshooting activity, audit, investigation, or recovery process.

Once the retention period has expired and the logs are no longer required, authorized personnel may archive or permanently delete them according to the CitiCare log management process.

# 6. Extraction Data Contract and Naming Convention


The CitiCare Extraction Data Contract defines the required structure, data types, identifiers, naming rules, and field mappings for data exported from the PostgreSQL database into CSV files. These rules ensure that the extracted data remains consistent and can be reliably processed by Python before proceeding to the Transformation Stage.

### 1. Required Schema

The following datasets and fields are required for the CitiCare extraction process.

#### `residents.csv`

| Column | Data Type | Constraint |
|---|---|---|
| `resident_id` | BIGINT | Primary Key, Required, Unique |
| `purok_id` | BIGINT | Foreign Key, Required |
| `risk_level` | TEXT | Required |

#### `resident_chronic_conditions.csv`

| Column | Data Type | Constraint |
|---|---|---|
| `condition_id` | BIGINT | Primary Key, Required, Unique |
| `resident_id` | BIGINT | Foreign Key, Required |
| `condition_name` | TEXT | Required |
| `created_at` | TIMESTAMP | Required |

#### `schedules.csv`

| Column | Data Type | Constraint |
|---|---|---|
| `schedule_id` | BIGINT | Primary Key, Required, Unique |
| `resident_id` | BIGINT | Foreign Key, Required |
| `date` | DATE | Required |
| `status` | TEXT | Required |

#### `puroks.csv`

| Column | Data Type | Constraint |
|---|---|---|
| `purok_id` | BIGINT | Primary Key, Required, Unique |
| `name` | TEXT | Required |

Primary keys must contain unique and non-null values. Foreign keys must use the same identifier names as the primary keys they reference to maintain consistency between related datasets.

The incremental window columns `updated_at` and `created_at` are exported when present in the source table. They are required only for extraction filtering and are not required transformation inputs. If a dataset has no window column, the extraction logs a warning and the run requires manual review.

### 2. Naming Convention

CitiCare uses the following naming conventions for extracted data:

- **Table and file names** use lowercase `snake_case`, such as `residents.csv`, `resident_chronic_conditions.csv`, and `schedules.csv`.
- **Column names** use lowercase `snake_case`, such as `resident_id`, `risk_level`, and `condition_name`.
- **Primary keys** use the entity name followed by `_id`, such as `resident_id`, `condition_id`, and `schedule_id`.
- **Foreign keys** use the same name as the referenced primary key. The `resident_id` in `resident_chronic_conditions` references the `resident_id` in `residents`.
- **Date and timestamp fields** use descriptive and consistent names such as `date` and `created_at`.
- Unclear or unnecessary abbreviations should be avoided.
- The same field must use the same standardized name throughout the pipeline unless an approved mapping is documented.

### Source-to-Standardized Field Mapping

The current CitiCare source fields already follow the standardized naming convention used by the pipeline. Therefore, most fields use a **Direct** mapping, meaning that no renaming or data type conversion is required during extraction.

| Source Column | Standardized Column | Source Type | Target Type | Mapping Type |
|---|---|---|---|---|
| `resident_id` | `resident_id` | BIGINT | BIGINT | Direct |
| `purok_id` | `purok_id` | BIGINT | BIGINT | Direct |
| `risk_level` | `risk_level` | TEXT | TEXT | Direct |
| `condition_id` | `condition_id` | BIGINT | BIGINT | Direct |
| `condition_name` | `condition_name` | TEXT | TEXT | Direct |
| `created_at` | `created_at` | TIMESTAMP | TIMESTAMP | Direct |
| `schedule_id` | `schedule_id` | BIGINT | BIGINT | Direct |
| `date` | `date` | DATE | DATE | Direct |
| `status` | `status` | TEXT | TEXT | Direct |
| `name` | `name` | TEXT | TEXT | Direct |
| `created_at` | `created_at` | TIMESTAMP | TIMESTAMP | Direct (window column) |
| `updated_at` | `updated_at` | TIMESTAMP | TIMESTAMP | Direct (window column, when present) |

A **Direct** mapping means that the source column name and data type already match the standardized field expected by the pipeline. If a source field uses a different name or data type in the future, the mapping must be documented before the data is accepted by the pipeline.

### 3. Schema Consistency

Python validates the structure of each exported CSV file before the extracted data proceeds to the Transformation Stage.

The following rules apply:

- If a **required column is missing**, the affected dataset fails schema validation.
- If a **required column is renamed**, the dataset fails validation unless an approved source-to-standardized mapping exists.
- If a column contains an **unexpected data type**, the issue is recorded and the affected dataset is prevented from proceeding until the type is corrected or an approved type mapping is defined.
- If an **unexpected additional column** appears, it is logged for review and does not automatically become part of the standardized schema.
- Changes to primary keys, foreign keys, required fields, or data types must be documented before they are accepted by the pipeline.
- Any detected schema inconsistency is recorded in the extraction validation results and extraction logs.

Only data that satisfies the required schema and approved mappings will proceed from Extraction Validation to the Transformation Stage.

# 7. Extraction Acceptance and Handover Rules

The CitiCare extraction acceptance and handover rules determine whether the raw extracted data is ready to proceed to the Transformation Stage. The decision is based on the results of the extraction validation checks.

### Decision Rules

| Validation Condition | Acceptance Criteria | Decision | Pipeline Action | Decision Type | Responsible Role |
|---|---|---|---|---|---|
| All critical validation checks pass | Required CSV files and columns are present, required identifiers are valid, primary keys are unique, record counts match, and no critical extraction errors are detected | **APPROVED** | Proceed to the Transformation Stage | Automatic | Pipeline |
| Non-critical validation warning is detected | Data remains usable, but minor issues such as unexpected additional columns or unusual record counts require verification | **MANUAL REVIEW** | Hold the affected data until the warning is reviewed | Manual | System Administrator / Developer |
| Required CSV file or column is missing | One or more required datasets or fields are unavailable | **REJECTED** | Stop processing the affected dataset and record the failure in the extraction log | Automatic | Pipeline |
| Required identifier is missing or invalid | Required primary or foreign key values are missing or cannot be validated | **REJECTED** | Quarantine the affected data and record the validation failure | Automatic | Pipeline |
| Duplicate primary keys are detected | Primary key uniqueness validation fails | **REJECTED** | Quarantine the affected data for correction | Automatic | Pipeline |
| Extracted record count does not reconcile | Records extracted plus records rejected do not equal records read | **REJECTED** | Stop the affected extraction and retry after checking the source CSV file | Automatic | Pipeline |
| Extraction checkpoint is missing or unreadable | The stored incremental boundary cannot be parsed, so the next window cannot be determined | **FAILED** | Stop the extraction and rebuild the checkpoint from the last approved run | Automatic | System Administrator / Developer |
| Source database is unreachable or credentials fail | Python cannot connect to or read the PostgreSQL source | **FAILED** | Stop the extraction, record the connection error, and retry after connectivity or credentials are corrected | Automatic | Pipeline / System Administrator |
| Extraction is interrupted or a critical reading error occurs | Python cannot completely read or extract the required CSV data | **FAILED** | Stop the extraction, record the error, and retry after the issue is resolved | Automatic | Pipeline |

### Automatic Approval

Extracted data is automatically approved when all critical validation checks return **PASS**. This includes successful source connectivity and file accessibility, presence of required datasets and columns, valid required identifiers, unique primary keys, matching record counts, valid extraction windows, and completion without critical extraction errors.

When these conditions are satisfied, the pipeline automatically passes the validated raw extracted data to the Transformation Stage.

### Manual Review

Manual review is required when the extraction produces a **WARNING** that does not immediately make the data unusable. This may include unexpected additional columns, a non-standard column name, or a dataset that had to be extracted in full because no supported window column was available.

The affected data is temporarily held while the **System Administrator or Developer** reviews the warning. If the issue is determined to be acceptable, the extraction may be approved and passed to the Transformation Stage. If the issue affects data reliability, the extraction is rejected for correction.

A `MANUAL REVIEW` run publishes its data with `handover_status = HELD`, so Stage 2 refuses it. The authorized reviewer records approval with `py run_pipeline.py --approve --reviewer "<name>"`, which changes the marker to `APPROVED` and updates the checkpoint; the reviewed data itself is not modified.

### Rejection or Failure

Extracted data is rejected when a critical validation check fails. Critical failures include missing required files or columns, invalid required identifiers, duplicate primary keys, incomplete extraction, an unreadable extraction checkpoint, or critical extraction errors.

Records that fall outside the monthly extraction window are excluded from the handover and counted in `Records Rejected`; they do not fail the run, because they belong to an earlier window.

Rejected or affected data is **quarantined** to prevent it from entering the Transformation Stage. If the failure is caused by an extraction interruption or temporary file-reading problem, the extraction may be retried after the issue is corrected. All failures and retry results are recorded in the extraction logs.

### Handover

Once an extraction run is approved, the following information is handed over to the Transformation Stage:

- Validated raw extracted data
- Pipeline run ID
- Source CSV file name
- Extraction window
- Extraction start and end timestamps
- Number of records read
- Number of records extracted
- Number of records rejected
- Validation results
- Extraction status
- Error or warning information, if applicable

Only data with an **APPROVED** extraction status is automatically handed over to the Transformation Stage.

### Validation Summary

| Validation Check | Required Result |
|---|---|
| Source connectivity | PASS |
| Source file accessibility | PASS |
| Required datasets/files | PASS |
| Required columns | PASS |
| Required identifiers | PASS |
| Primary key uniqueness | PASS |
| Record count and extraction completeness | PASS |
| Incremental extraction window | PASS |
| Extraction completion and error check | PASS |
| **Overall Extraction** | **APPROVED** |

If any non-critical check returns a **WARNING**, the overall extraction status becomes **MANUAL REVIEW**. If any critical check returns **FAIL**, the overall extraction status becomes **REJECTED** or **FAILED**, and the affected data cannot proceed to the Transformation Stage.

# 8. Common Extraction Problems and Mitigation

The CitiCare extraction process may encounter issues when health records are exported from the PostgreSQL database into CSV files and subsequently extracted using Python. The following problems and mitigation measures are defined to maintain extraction completeness and reliability.

This stage performs **no record cleaning, value standardization, health classification, or business transformation**. Missing values are rejected or quarantined rather than corrected, duplicate keys are rejected rather than merged, and `condition_name`, `risk_level`, and `status` values are not normalized here. All such work belongs to the Transformation Stage.

| Problem | Possible Cause | Impact on Extraction | Proposed Solution / Mitigation |
|---|---|---|---|
| Source database unavailable | The PostgreSQL server is offline, the network is unreachable, or credentials have expired. | Python cannot export the required datasets, so the run cannot start or complete. | Confirm connectivity and credentials before the scheduled run, record `CONNECTION_ERROR`, and retry after access is restored. |
| Missing CSV file | A required dataset was not exported from the PostgreSQL database or was saved in the wrong directory. | Python cannot extract the required dataset, resulting in an incomplete extraction run. | Verify that all required CSV files are present before extraction. Stop the affected extraction and record the missing file in the extraction log. |
| Missing or changed columns | A column was removed, renamed, or changed in the PostgreSQL source before CSV export. | The exported CSV may no longer match the required schema, causing validation or processing errors. | Validate CSV columns against the documented schema. Reject the affected dataset until the column is restored or an approved field mapping is defined. |
| Duplicate records | The same records may be included more than once in the exported CSV file. | Duplicate records may produce inaccurate counts and analytical results. | Check primary key uniqueness during extraction validation and quarantine duplicate records for review. Duplicates are not merged in this stage. |
| Missing required identifiers | Required identifiers such as `resident_id`, `purok_id`, or other primary and foreign keys contain null or missing values. | Records may not be correctly identified or linked to related health records. | Validate required identifiers before handover. Reject or quarantine affected records until the issue is corrected; do not impute identifiers. |
| Incorrect incremental extraction window | The stored checkpoint is missing, stale, or uses a different timezone, so the wrong date conditions are applied. | Records may be missed or records from previous extraction periods may be extracted again. | Compare extracted window values with the stored checkpoint, normalize all timestamps to UTC, and update the checkpoint only after an approved run. Use a documented backfill for late-arriving records. |
| Record count mismatch | Python reads fewer records than the number contained in the exported CSV file due to incomplete reading, malformed rows, or interruption. | The extracted dataset may be incomplete and should not proceed to transformation. | Compare `records read`, `records extracted`, and `records rejected` for every dataset. Stop the affected dataset when the counts do not reconcile and investigate before retrying. |
| Invalid or malformed CSV data | The CSV file contains malformed rows, incorrect delimiters, encoding problems, or improperly formatted values. | Python may fail to read some or all records from the CSV file. | Validate file readability and CSV structure before processing. Record parsing errors and quarantine affected data for correction. |
| Extraction process interruption | Python execution is interrupted because of a system error, unavailable file, or unexpected program failure. | The extraction may stop before all required records are processed, resulting in partial data. | Mark the extraction run as `FAILED` or `PARTIAL`, record the error in the extraction log, and retry the extraction after the cause has been resolved. |