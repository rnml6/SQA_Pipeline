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

**Extraction Type:** Batch Extraction  
**Extraction Tool:** Python

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

CitiCare uses an **incremental extraction** method to retrieve newly added or updated health records from the PostgreSQL database. Instead of extracting the entire database during every pipeline run, only records that have been created or modified since the previous extraction are selected.

The extraction window is determined using a timestamp field. The pipeline stores the timestamp of the previous successful extraction and uses it as the starting point for the next extraction

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

**Reason for inclusion:** Resident information is required to identify residents and support risk classification and purok-level health analysis.

---

## 2.2 `resident_chronic_conditions`

### Purpose

The `resident_chronic_conditions` table contains chronic conditions recorded for residents.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `condition_id` | BIGINT | Primary Key | Unique identifier of the chronic condition record |
| `resident_id` | BIGINT | Foreign Key → `residents(resident_id)` | Identifies the resident who has the condition |
| `condition_name` | TEXT | — | Name of the chronic condition |
| `created_at` | TIMESTAMP | — | Indicates when the condition was recorded |

**Reason for inclusion:** Chronic condition records are required for disease prevalence and resident health analysis.

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

**Reason for inclusion:** Schedule records are required to identify and analyze missed health consultations.

---

## 2.4 `puroks`

### Purpose

The `puroks` table contains the purok information used to organize residents geographically within the barangay.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `purok_id` | BIGINT | Primary Key | Unique identifier of the purok |
| `name` | TEXT | — | Name of the purok |

**Reason for inclusion:** Purok information is required to group resident health information and support purok-level prioritization and analysis.

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


| Check Name | Target | Purpose | Validation Criteria |
|---|---|---|---|
| Source Files | Exported CSV datasets | Verify that source datasets are available | Required CSV files are found |
| Required Tables / Datasets | All required source data | Ensure required datasets are included | All required datasets are available |
| Required Columns | Selected columns | Ensure required fields exist | All required columns exist |
| Identifier Presence | Primary and foreign keys | Ensure records can be identified and related | Required identifiers are present |
| Primary Key Uniqueness | Primary key columns | Detect duplicate identifiers | No duplicate primary keys |
| Record Count | Extracted datasets | Verify records were retrieved | Record counts are successfully recorded |
| Extraction Completeness | Extraction result | Detect incomplete extraction | Extraction completes without interruption |
| Foreign Key Availability | Relationship columns | Verify relationships can be maintained | Required foreign-key values are present |
| Extraction Error Check | Extraction process | Detect failures or interruptions | No unhandled extraction error |
| Extraction Status | Pipeline run | Determine the result of extraction | Status is recorded as PASS, WARNING, or FAIL |

---
# 4. Extraction Metadata and Log Specification


The CitiCare extraction process records metadata and logs for every extraction run. These records provide information about when the extraction occurred, which CSV files were processed, how many records were handled, whether validation was successful, and whether any errors occurred.

| Metadata / Log Field | Purpose | Example Value / Format |
|---|---|---|
| Pipeline Run ID | Provides a unique identifier for each extraction run. | `CITICARE_EXT_20261001_001` |
| Table / File Name | Identifies the PostgreSQL table or exported CSV file being processed. | `residents.csv` |
| Extraction Start Timestamp | Records when Python started extracting data from the CSV file. | `2026-10-01 08:00:00` |
| Extraction End Timestamp | Records when the extraction process finished. | `2026-10-01 08:02:15` |
| Extraction Status | Indicates whether the extraction completed successfully. | `Success`, `Failed`, `Partial` |
| Records Read | Records the total number of records read from the exported CSV file. | `350` |
| Records Extracted | Records the number of records successfully extracted and accepted as raw data. | `347` |
| Records Rejected | Records the number of records rejected because of extraction or validation issues. | `3` |
| Extraction Window | Identifies the monthly period covered by the incremental extraction. | `2026-09-01 to 2026-09-30` |
| Validation Results | Records the result of the extraction validation checks. | `Passed` or `Failed: 3 missing resident_id values` |
| Error Message / Code | Records details of errors encountered during extraction. | `NULL` if successful; `CSV_READ_ERROR` if failed |
| Extraction Duration | Measures the total time required to complete the extraction. | `00:02:15` |

The **Pipeline Run ID** is used to identify and group CSV files processed during the same monthly extraction run. Each CSV file maintains its own log entry so that its record counts, validation results, and extraction status can be individually monitored.

### Use of Extraction Metadata and Logs

The extraction metadata and logs are used for **monitoring, troubleshooting, auditing, and recovery**.

- **Monitoring** — Extraction status, timestamps, record counts, and duration are used to verify that the monthly extraction completed successfully.
- **Troubleshooting** — Validation results and error messages help identify missing files, invalid records, CSV reading errors, or interrupted extraction processes.
- **Auditing** — The pipeline run ID, extraction window, file names, and record counts provide a traceable history of the data processed during each monthly extraction.
- **Recovery** — Failed or partially completed extraction runs can be identified through their run ID and status. The affected CSV files can then be corrected and reprocessed before proceeding to the Transformation Stage.

# 5. Log Retention and Access

The CitiCare extraction logs are retained to provide a reliable history of pipeline activities and to support monitoring, troubleshooting, auditing, and recovery. Logs are managed to ensure that extraction records remain available when needed while preventing unnecessary long-term storage.

| Log Management Area | Specification |
|---|---|
| Log Retention Period | Extraction logs will be retained for **12 months**. This period allows previous monthly extraction runs to be reviewed for troubleshooting, auditing, comparison, and recovery purposes. |
| Storage Location | Extraction logs will be stored in a dedicated **logs directory** within the CitiCare ETL environment. |
| Access Permissions | Access to extraction logs will be limited to **authorized developers or system administrators** responsible for maintaining and monitoring the ETL pipeline. |
| Archiving Requirements | Logs older than the active operational period may be moved to an **archive directory** while still within the 12-month retention period. Archived logs must remain accessible when required for auditing or recovery. |
| Deletion Rules | Logs may only be deleted after the **12-month retention period** and when they are no longer required for troubleshooting, auditing, or recovery. |
| Responsible Process | Log deletion and archiving will be handled through the pipeline's **log management process** under the supervision of an authorized system administrator or developer. |

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
| Extracted record count does not match the CSV record count | Extraction completeness cannot be confirmed | **REJECTED** | Stop the affected extraction and retry after checking the source CSV file | Automatic | Pipeline |
| Records fall outside the monthly extraction window | Extracted records do not satisfy the defined incremental extraction period | **REJECTED** | Quarantine the affected records and record the issue in the extraction log | Automatic | Pipeline |
| Extraction is interrupted or a critical reading error occurs | Python cannot completely read or extract the required CSV data | **FAILED** | Stop the extraction, record the error, and retry after the issue is resolved | Automatic | Pipeline |

### Automatic Approval

Extracted data is automatically approved when all critical validation checks return **PASS**. This includes successful file accessibility, presence of required datasets and columns, valid required identifiers, unique primary keys, matching record counts, valid extraction windows, and completion without critical extraction errors.

When these conditions are satisfied, the pipeline automatically passes the validated raw extracted data to the Transformation Stage.

### Manual Review

Manual review is required when the extraction produces a **WARNING** that does not immediately make the data unusable. This may include unexpected additional columns or unusual record counts that still match the extracted CSV data.

The affected data is temporarily held while the **System Administrator or Developer** reviews the warning. If the issue is determined to be acceptable, the extraction may be approved and passed to the Transformation Stage. If the issue affects data reliability, the extraction is rejected for correction.

### Rejection or Failure

Extracted data is rejected when a critical validation check fails. Critical failures include missing required files or columns, invalid required identifiers, duplicate primary keys, incomplete extraction, records outside the defined extraction window, or critical extraction errors.

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
| Source accessibility | PASS |
| Required datasets/files | PASS |
| Required columns | PASS |
| Required identifiers | PASS |
| Primary key uniqueness | PASS |
| Record count and extraction completeness | PASS |
| Incremental extraction window | PASS |
| Extraction error check | PASS |
| **Overall Extraction** | **APPROVED** |

If any non-critical check returns a **WARNING**, the overall extraction status becomes **MANUAL REVIEW**. If any critical check returns **FAIL**, the overall extraction status becomes **REJECTED** or **FAILED**, and the affected data cannot proceed to the Transformation Stage.

# 8. Common Extraction Problems and Mitigation

The CitiCare extraction process may encounter issues when health records are exported from the PostgreSQL database into CSV files and subsequently extracted using Python. The following problems and mitigation measures are defined to maintain extraction completeness and reliability.

| Problem | Possible Cause | Impact on Extraction | Proposed Solution / Mitigation |
|---|---|---|---|
| Missing CSV file | A required dataset was not exported from the PostgreSQL database or was saved in the wrong directory. | Python cannot extract the required dataset, resulting in an incomplete extraction run. | Verify that all required CSV files are present before extraction. Stop the affected extraction and record the missing file in the extraction log. |
| Missing or changed columns | A column was removed, renamed, or changed in the PostgreSQL source before CSV export. | The exported CSV may no longer match the required schema, causing validation or processing errors. | Validate CSV columns against the documented schema. Reject the affected dataset until the column is restored or an approved field mapping is defined. |
| Duplicate records | The same records may be included more than once in the exported CSV file. | Duplicate records may produce inaccurate counts and analytical results. | Check primary key uniqueness during extraction validation and quarantine duplicate records for review. |
| Missing required identifiers | Required identifiers such as `resident_id`, `purok_id`, or other primary and foreign keys contain null or missing values. | Records may not be correctly identified or linked to related health records. | Validate required identifiers before handover. Reject or quarantine affected records until the issue is corrected. |
| Incorrect incremental extraction window | Incorrect date or change-tracking conditions are used when selecting records for the monthly export. | Records may be missed or records from previous extraction periods may be extracted again. | Validate the extraction date range and store the previous successful extraction timestamp for use in determining the next extraction window. |
| Record count mismatch | Python reads fewer records than the number contained in the exported CSV file due to incomplete reading, malformed rows, or interruption. | The extracted dataset may be incomplete and should not proceed to transformation. | Compare the number of records in the CSV with the number successfully extracted. Stop the affected dataset when the counts do not match and investigate before retrying. |
| Invalid or malformed CSV data | The CSV file contains malformed rows, incorrect delimiters, encoding problems, or improperly formatted values. | Python may fail to read some or all records from the CSV file. | Validate file readability and CSV structure before processing. Record parsing errors and quarantine affected data for correction. |
| Extraction process interruption | Python execution is interrupted because of a system error, unavailable file, or unexpected program failure. | The extraction may stop before all required records are processed, resulting in partial data. | Mark the extraction run as `FAILED` or `PARTIAL`, record the error in the extraction log, and retry the extraction after the cause has been resolved. |