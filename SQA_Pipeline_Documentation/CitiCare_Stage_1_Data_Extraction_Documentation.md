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
