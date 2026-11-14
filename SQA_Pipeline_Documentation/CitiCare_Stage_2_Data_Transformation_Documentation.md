# Stage 2: Data Transformation Documentation

## Objective

The objective of the Data Transformation process is to clean, standardize, validate, and prepare the extracted CitiCare datasets for the Data Loading Stage. All transformations must be documented, traceable, and validated before the transformed data is handed over for loading.

# 1. Transformation Input and Processing Specification

## 1.1 Input Source

The Data Transformation process receives the approved CSV files and extraction metadata from the Extraction Stage.

| Item | Specification |
|---|---|
| Input source | Approved Stage 1 extraction handover (not the source database) |
| Input files | `puroks.csv`, `residents.csv`, `resident_chronic_conditions.csv`, `schedules.csv` |
| Reference files | `reference/puroks.csv`, `reference/residents.csv` when the monthly batch is incremental |
| Handover metadata | `handover.json` |
| Format | CSV plus JSON metadata |
| Location | `Data_Pipelines/Extraction/data/handover/` |
| Extraction Run ID | `handover.json` → `pipeline_run_id`, recorded as `parent_run_id` |
| Batch window | `handover.json` → `batch_window` (or the recorded previous/current extraction boundary) |
| Required metadata | Extraction run ID, batch window, extraction status, input filenames, and record counts |
| Acceptance gate | Transformation starts only when `handover_status` (or `extraction_status`) is `APPROVED` |

The Data Transformation process consumes the handover package and never reconnects to the CitiCare PostgreSQL source. The source-system and database description is therefore not repeated here; it is defined once in the Stage 1 documentation. The Stage 1 handover is the sole input contract, and the Stage 2 input schema is the Stage 1 Section 6 data contract.

## 1.2 Batch Processing Method

| Item | Specification |
|---|---|
| Transformation tool | Python 3 |
| Supporting modules | `csv`, `json`, `datetime`, `pathlib`, `hashlib`, `collections`, `shutil` |
| Processing method | Monthly batch processing |
| Schedule | Monthly, aligned with the approved extraction schedule |
| Batch size | All approved records included in the extraction handover |
| Output | Transformed CSV datasets, validation results, metadata, manifest, audit records, and the quarantine table |
| Failure recovery | Record the error, preserve the input, correct the problem, and rerun the same batch |
| Idempotency | Guaranteed; reruns replace the same batch outputs and never append duplicates |

The transformation process must use deterministic rules and controlled output replacement or rebuilding for the same batch. Database loading is handled by the Data Loading Stage.

### Rerun and Idempotency

A failed or held batch is rerun through the following controlled procedure:

1. Read the failure record in `logs/transform.log` and the audit record under `logs/audit/<year>/FAILED_<run_id>.json`; the `error_code` identifies the failing control (`HANDOVER_NOT_APPROVED`, `SCHEMA_MISSING_COLUMN`, `CSV_READ_ERROR`, `PROCESSING_ERROR`, and so on).
2. Correct the cause without editing the approved extraction handover. Input data problems are corrected and re-approved in Stage 1, then handed over again.
3. Rerun with the same `parent_run_id` and `batch_window`. The `batch_id` is derived deterministically from the extraction run ID, so the rerun addresses the same batch identity.
4. Rebuild the batch output in a temporary directory (`.tmp_<batch_id>`) and replace `output/<batch_id>/` only after the whole batch succeeds.
5. Overwrite the batch's quarantine and profile files; never append to them.
6. Re-run every validation check before publishing. An aborted rerun leaves the previous published batch untouched.

Idempotency rules:

- Every rule is deterministic: the same input and rule version produce the same output rows in the same order (rows are sorted by primary key).
- Outputs are written per batch and replace the prior attempt of that batch, so a rerun cannot create duplicate residents, schedules, or conditions.
- Natural keys (`resident_id`, `condition_id`, `schedule_id`, `purok_id`) are preserved and no random or timestamp-derived surrogate key is generated.
- Quarantine rows are rebuilt for the batch, and `records_rejected`, `records_duplicates_excluded`, and `records_output` are recomputed rather than accumulated.
- The batch manifests record `run_id`, `batch_id`, code version, and rule version, so the replacement attempt is traceable.

## 1.3 Transformation Scope

| Input file | Fields in scope | Transformation purpose |
|---|---|---|
| `residents.csv` | `resident_id`, `purok_id`, `risk_level` | Validate identifiers, clean text values, and check purok relationships. |
| `resident_chronic_conditions.csv` | `condition_id`, `resident_id`, `condition_name`, `created_at` | Validate identifiers, standardize condition names and timestamps, and check resident relationships. |
| `schedules.csv` | `schedule_id`, `resident_id`, `date`, `status` | Validate identifiers, standardize dates and status values, and check resident relationships. |
| `puroks.csv` | `purok_id`, `name` | Validate identifiers, clean names, and prepare reference data. |

Cleaning, standardization, validation, and business transformation activities are described in the corresponding documentation headings below.

## 1.4 Dependencies and Assumptions

### Processing Order

1. Validate the extraction handover and required input files.
2. Profile all four datasets.
3. Clean the four datasets in parent-before-child order: `puroks`, `residents`, `resident_chronic_conditions`, `schedules`.
4. Standardize types, dates, timestamps, and approved codes for all four datasets.
5. Validate primary keys, foreign keys, and cross-file relationships.
6. Apply approved business transformation rules and validate join cardinality.
7. Validate and reconcile transformed outputs, including the rejection-rate threshold.
8. Package approved outputs, quarantine records, metadata, and the manifest for the Data Loading Stage.

### Dependencies and Assumptions

- The Extraction Stage provides the approved files, extraction run ID, batch window, record counts, and validation status.
- The datasets follow the documented extraction schema.
- The monthly batch window is determined by the extraction handover.
- Relationship checks require an approved reference dataset or previously validated parent records when monthly incremental files do not contain every referenced record.
- Late-arriving records are processed through a subsequent or explicitly rerun extraction handover.
- Missing lookup data and unresolved relationships must be reported and must not be silently ignored.
- Clinical classifications and allowed `risk_level` or `status` values must follow approved CitiCare definitions.
- Actual directory paths, input handover metadata, code versions, rule versions, and execution timestamps must be recorded in the batch manifest and audit record.

# 2. Data Profiling and Issue Identification

Profiling runs before any cleaning rule. Every issue below was measured against the approved handover for batch `BATCH_3d209da2` (parent extraction run `CITICARE_EXT_20261114_3d209da2`, profiled `2026-11-14T12:43:03Z`). The profile covers 59 records: `puroks` 7, `residents` 14, `resident_chronic_conditions` 9, and `schedules` 29.

| Issue ID | Table (file) | Column | Issue type | Sample value(s) | Affected records | Affected % | Planned treatment |
|---|---|---|---|---|---|---|---|
| P-01 | `puroks` (`puroks.csv`) | `purok_id` | Missing or duplicate identifier | none | 0 | 0.00% | Reject blank identifiers (C-01); quarantine duplicates (C-03) |
| P-02 | `puroks` (`puroks.csv`) | `name` | Leading/trailing whitespace or missing value | none | 0 | 0.00% | Trim whitespace (C-02); reject missing name (C-01) |
| P-03 | `puroks` (`puroks.csv`) | `name` | Invalid characters (no alphabetic content) | `212121` | 1 | 14.29% | Quarantine the record (C-06) |
| P-04 | `residents` (`residents.csv`) | `resident_id` | Missing or duplicate identifier | none | 0 | 0.00% | Reject blank identifiers (C-01); quarantine duplicates (C-03) |
| P-05 | `residents` (`residents.csv`) | `purok_id` | Missing or unmatched reference | none | 0 | 0.00% | Reject missing value (C-01); quarantine orphan reference (C-05) |
| P-06 | `residents` (`residents.csv`) | `risk_level` | Inconsistent text or unrecognized value | `Critical Risk`, `Low Risk`, `Moderate Risk`, `High Risk` | 14 | 100.00% | Clean text and apply the approved mapping (C-02, S-03, S-05) |
| P-07 | `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | `condition_id` | Missing or duplicate identifier | none | 0 | 0.00% | Reject blank identifiers (C-01); quarantine duplicates (C-03) |
| P-08 | `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | `resident_id` | Orphan relationship | none | 0 | 0.00% | Quarantine the record (C-05) |
| P-09 | `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | `condition_name` | Embedded document instead of a condition name | `{"name":"1","severity":"Severe"}` | 8 | 88.89% | Correct to the documented name member (C-06, S-07) or quarantine (C-04) |
| P-10 | `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | `condition_name` | Whitespace or inconsistent casing | `{"name":"hypertension","severity":"Mild"}` | 8 | 88.89% | Trim and apply the approved naming convention (C-02, S-07) |
| P-11 | `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | `created_at` | Invalid timestamp format | none | 0 | 0.00% | Convert to ISO 8601 or quarantine (S-02) |
| P-12 | `schedules` (`schedules.csv`) | `schedule_id` | Missing or duplicate identifier | none | 0 | 0.00% | Reject blank identifiers (C-01); quarantine duplicates (C-03) |
| P-13 | `schedules` (`schedules.csv`) | `resident_id` | Orphan relationship | none | 0 | 0.00% | Quarantine the record (C-05) |
| P-14 | `schedules` (`schedules.csv`) | `date` | Invalid or inconsistent date | none | 0 | 0.00% | Convert to ISO 8601 date or quarantine (S-01) |
| P-15 | `schedules` (`schedules.csv`) | `status` | Inconsistent or unrecognized value | `Completed`, `Missed`, `Cancelled` | 29 | 100.00% | Clean text and apply the approved mapping (C-02, S-03, S-06) |
| P-16 | all four files | all text columns | Leading/trailing or repeated whitespace | none | 0 | 0.00% | Trim and collapse whitespace (C-02) |

Affected percentage is calculated per source file: `affected_records / records_in_file × 100`. P-16 is measured across all 59 records. A zero count is a measured result for this batch, not an assumption that the issue cannot occur; the rule remains active for future batches. Each new batch must be re-profiled and its measured values recorded in `logs/profile/profile_<batch_id>.json` before cleaning.

# 3. Data Cleaning Rules

The following rules define how identified data-quality issues are handled. Their application and record counts must be captured in the transformation logs. Each fired rule is also written to `metadata.json` as `rule_trace`, which records the measured profile issue IDs (P-01 to P-16) the rule traces back to together with the number of affected records.

| Rule ID | Target | Condition | Action | Profiled issue(s) | Justification |
|---|---|---|---|---|---|
| C-01: Required values | Required columns in all four files | Required identifier or field is null, empty, or whitespace-only | Reject the affected record to quarantine with `MISSING_REQUIRED_VALUE`. | P-01, P-02, P-04, P-05, P-07, P-08, P-11, P-12, P-13, P-14 | Prevents incomplete records from entering the transformed output; no defaults or imputation are used. |
| C-02: Whitespace cleanup | Text fields in all four files | Leading/trailing whitespace, repeated internal spaces, control characters, or zero-width characters exist | Trim, collapse, and remove the disallowed characters; log the affected record as modified. | P-02, P-10, P-16 | Prevents inconsistent matching and formatting without changing meaning. |
| C-03: Duplicate identifiers | `resident_id`, `condition_id`, `schedule_id`, `purok_id` | Duplicate primary key exists | Keep one authoritative record using the deterministic survivor rule below and quarantine every superseded record with `DUPLICATE_PRIMARY_KEY_SUPERSEDED`. | P-01, P-04, P-07, P-12 | Produces a unique key while preserving every superseded record and a deterministic rerun result. |
| C-04: Invalid values | `condition_name` and other validated non-code fields | Value is a placeholder, contains no usable alphabetic name, or violates an approved field rule | Quarantine the record with the applicable rule ID and reason code. | P-09 | Prevents unsupported values from entering the output while retaining traceability. |
| C-05: Orphan relationships | `residents.purok_id`, `resident_chronic_conditions.resident_id`, `schedules.resident_id` | Referenced parent cannot be found in the approved reference set | Quarantine the record with `ORPHAN_FOREIGN_KEY` and record the missing reference. | P-05, P-08, P-13 | Preserves referential integrity without silently dropping data. |
| C-06: Invalid characters | Text fields | Characters violate an explicitly approved field rule, such as a purok name with no alphabetic character or an embedded JSON document in `condition_name` | Apply only the approved correction (keep the documented `name` member); otherwise quarantine under C-04. | P-03, P-09 | Avoids damaging valid names or descriptions through indiscriminate character removal. |

### Duplicate Handling (C-03 Survivor Rule)

When a primary key occurs more than once, exactly one record is kept and the others are quarantined. The survivor is chosen deterministically:

1. **Latest timestamp:** the record with the latest parseable `updated_at`; if no `updated_at` is available, the latest parseable `created_at`.
2. **Most complete record:** if timestamps are absent or equal, the record with the most non-empty fields.
3. **Canonical tie-break:** if records are still tied, the lexicographically smallest canonical serialization of the cleaned row.

All superseded duplicates are written to the quarantine table with `rule_id = C-03`, `reason_code = DUPLICATE_PRIMARY_KEY_SUPERSEDED`, and a reason naming the retained key. The retained record appears once in the output. The number of superseded records is reported as `records_duplicates_excluded` and is not double-counted in `records_rejected`.

### Record Handling

Missing values must not be replaced with arbitrary defaults. Invalid or out-of-range values must be handled according to approved field-specific rules. Records that are cleaned and retained count as modified, not rejected. Every rejected record receives a quarantine row containing its batch ID, rule ID, source file, source key, column, raw value, reason code, and reason.

# 4. Standardization and Data Type Rules

## 4.1 Data Types and Formats

| Rule ID | Column | Input representation | Target type and format | Precision / range | On conversion failure |
|---|---|---|---|---|---|
| S-01 | `schedules.date` | CSV text, `YYYY-MM-DD` | ISO 8601 date, `YYYY-MM-DD`, no time component or timezone | Calendar date within 1900-01-01 to 2100-12-31 | Quarantine with `INVALID_DATE` |
| S-02 | `resident_chronic_conditions.created_at` | CSV text, ISO 8601 date or timestamp | ISO 8601 UTC timestamp, `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` | Microsecond precision preserved; naive values interpreted as UTC | Quarantine with `INVALID_TIMESTAMP` |
| S-03 | `puroks.name`, `risk_level`, `status`, `condition_name` | CSV text | Trimmed, consistently formatted text (Title Case for names; approved upper-case codes for risk and status) | Maximum 200 characters after cleaning | Quarantine the value if it cannot be safely normalized under its field rule |
| S-04 | `resident_id`, `purok_id`, `condition_id`, `schedule_id` | CSV text representation of an identifier | Signed 64-bit integer, scale 0 | 1 to 9,223,372,036,854,775,807 | Quarantine with `INVALID_IDENTIFIER` |
| S-08 | Any future numeric measure | CSV text | `DECIMAL(12,2)` | 2 decimal places, half-up rounding | Reject the batch schema until an approved precision and range rule exists |

**Date and time rules**

- Dates and timestamps are parsed only in ISO 8601 form. Locale-specific formats such as `MM/DD/YYYY` or month names are not accepted.
- All timestamps are normalized to UTC. A timezone is applied only when the source contract defines it; the CitiCare source contract stores UTC, so a naive timestamp is treated as UTC rather than the host locale.
- Date-only fields remain dates and are never combined with an arbitrary time of day.
- Microseconds are preserved where present and are not rounded.

**Conversion-failure rule**

Every conversion failure is a controlled rejection, not a silent default: the record is written to quarantine with the rule ID, error code, column, and raw value, and processing continues with the remaining records. A failed conversion is never replaced with a guessed value. If the resulting rejection rate exceeds the approved threshold, the batch is held for manual review under Section 10.

## 4.2 Reference Values and Codes

| Rule ID | Field | Approved input values (case-insensitive) | Output code | On failure |
|---|---|---|---|---|
| S-05 | `risk_level` | `LOW`, `LOW RISK` → `LOW`; `MODERATE`, `MODERATE RISK` → `MODERATE`; `HIGH`, `HIGH RISK` → `HIGH`; `CRITICAL`, `CRITICAL RISK` → `CRITICAL` | `LOW`, `MODERATE`, `HIGH`, `CRITICAL` | Quarantine with `UNRECOGNIZED_RISK_LEVEL` |
| S-06 | `schedules.status` | `COMPLETED`, `COMPLETE`, `DONE` → `COMPLETED`; `MISSED`, `NO SHOW` → `MISSED`; `CANCELLED`, `CANCELED` → `CANCELLED` | `COMPLETED`, `MISSED`, `CANCELLED` | Quarantine with `UNRECOGNIZED_SCHEDULE_STATUS` |
| S-07 | `condition_name` | Trimmed text or an embedded document with a usable `name` member | Title Case condition name; placeholders, names with digits, or names with fewer than three alphabetic characters are rejected | Quarantine with `INVALID_CONDITION_NAME` |

No new clinical risk categories, schedule statuses, or medical classifications may be invented. A value outside the approved mapping is quarantined and reported; it is never mapped to the nearest code.

## 4.3 Numeric Precision

The approved input fields are identifiers, text, dates, and timestamps. Identifiers are whole numbers and must not contain decimal points, thousands separators, or exponent notation.

No numeric business measure requiring decimal precision is currently in scope. Rule **S-08** reserves `DECIMAL(12,2)` with half-up rounding for any future measure; such a field must not be added until its precision, range, and rounding rule are approved and added to the output contract.

# 5. Business Transformation Rules

The Data Transformation process prepares cleaned records for resident, chronic-condition, schedule, and purok-level analysis. Every rule has an ID, defined logic, an output target, and a business reason. A rule that is not approved for output is explicitly marked deferred rather than invented.

| Rule ID | Input columns | Logic | Output column / table | Business reason | Status |
|---|---|---|---|---|---|
| B-01: Resident–purok join | `residents.purok_id`, `puroks.purok_id` | Left-join `residents` to the approved purok reference on `purok_id`; validate 1:N cardinality; unmatched residents are already quarantined by C-05. No purok attribute is added because the output contract does not request enrichment. | Validated `residents.purok_id`; no new column | Confirms every resident belongs to an approved purok and supports purok-level analysis. | Applied |
| B-02: Resident condition count | `resident_chronic_conditions.resident_id`, `condition_id` | Group valid conditions by `resident_id` and count distinct `condition_id`. Requires a separately approved derived schema. | `condition_count` in a future `dim_residents` table (reserved, not emitted) | Supports chronic-condition summaries per resident. | Deferred — no approved derived schema |
| B-03: Schedule summary | `schedules.resident_id`, `status`, `date` | Group valid schedules by resident, status, and month; count schedules. Requires a separately approved derived schema. | Future `fact_schedule_summary` table (reserved, not emitted) | Supports consultation follow-up and missed-visit trends. | Deferred — no approved derived schema |
| B-04: Purok summary | `residents.purok_id`, `puroks.name`, validated measures | Group approved resident and health measures by purok. Requires a separately approved derived schema. | Future `fact_purok_summary` table (reserved, not emitted) | Supports community-level reporting and prioritization. | Deferred — no approved derived schema |
| B-05: Business exclusion | All datasets and validation results | Exclude records that fail a mandatory C- or S-rule from business-ready outputs; preserve each in quarantine with rule ID and reason. | No output column; quarantine table | Prevents invalid records from contaminating reports while preserving traceability. | Applied |
| B-06: Cancelled-schedule filter | `schedules.status` | `CANCELLED` is a valid approved status. No schedule is filtered out by status; cancelled appointments are retained and identified by `status = 'CANCELLED'`. | `schedules.status` | Excluding cancelled consultations would distort appointment history and missed-visit rates; downstream consumers may filter on the status explicitly. | Applied |
| B-07: Key policy (natural vs surrogate) | All primary and foreign keys | Retain natural keys (`resident_id`, `condition_id`, `schedule_id`, `purok_id`). Do not generate surrogate keys because no dimensional model is approved. | Natural keys in all four outputs | Guarantees deterministic reruns, stable lineage, and no orphaned surrogate mappings; dimensional keys belong to the Data Loading Stage. | Applied |
| B-08: Derived-column policy | All outputs | Emit only columns listed in the approved output contract. No derived analytical column is currently approved; any addition requires a new rule ID, output column, and schema version. | None (no derived column emitted) | Prevents undocumented analytics from entering the curated layer. | Applied as policy |

### Join, Filter, and Aggregation Requirements

- Use the documented keys: `residents.purok_id` references `puroks.purok_id`; `resident_chronic_conditions.resident_id` and `schedules.resident_id` reference `residents.resident_id`.
- Validate join cardinality to prevent unexpected row multiplication; an unmatched or multiplied join fails V-06.
- Unmatched records must be counted and quarantined or held for review.
- Aggregations must use validated records and documented grouping levels.
- Since extraction is monthly, a summary based only on the current batch must be identified as batch-scoped. Complete historical summaries require an approved historical dataset or prior validated state.
- Status-based filters must be explicit and documented. The only approved decision is B-06: cancelled schedules are retained, not excluded.
- No clinical score, diagnosis, or risk classification may be derived unless an approved business rule defines the logic.
- Every business exclusion must be counted, logged, and assigned a reason.
- If a dimensional layer is later approved, `dim_` and `fact_` prefixes and surrogate keys must follow Section 6.2; they are not created in this stage.

# 6. Transformed Data Contract and Naming Convention

## 6.1 Required Output Schema

The transformed output is an **atomic, source-aligned layer** of four tables. It is not a star schema: no dimension or fact table is emitted in this stage, and the keys remain the natural CitiCare identifiers.

| Output table (file) | Layer | Column | Target type | Nullability and constraints |
|---|---|---|---|---|
| `puroks` (`puroks.csv`) | Atomic reference | `purok_id` | 64-bit integer | Required, unique primary key |
| `puroks` (`puroks.csv`) | Atomic reference | `name` | Text | Required |
| `residents` (`residents.csv`) | Atomic entity | `resident_id` | 64-bit integer | Required, unique primary key |
| `residents` (`residents.csv`) | Atomic entity | `purok_id` | 64-bit integer | Required foreign key → `puroks.purok_id` |
| `residents` (`residents.csv`) | Atomic entity | `risk_level` | Text code | Required; one of `LOW`, `MODERATE`, `HIGH`, `CRITICAL` |
| `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | Atomic entity | `condition_id` | 64-bit integer | Required, unique primary key |
| `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | Atomic entity | `resident_id` | 64-bit integer | Required foreign key → `residents.resident_id` |
| `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | Atomic entity | `condition_name` | Text | Required |
| `resident_chronic_conditions` (`resident_chronic_conditions.csv`) | Atomic entity | `created_at` | ISO 8601 UTC timestamp | Required |
| `schedules` (`schedules.csv`) | Atomic entity | `schedule_id` | 64-bit integer | Required, unique primary key |
| `schedules` (`schedules.csv`) | Atomic entity | `resident_id` | 64-bit integer | Required foreign key → `residents.resident_id` |
| `schedules` (`schedules.csv`) | Atomic entity | `date` | ISO 8601 date | Required |
| `schedules` (`schedules.csv`) | Atomic entity | `status` | Text code | Required; one of `COMPLETED`, `MISSED`, `CANCELLED` |

Any derived summary output must have a separately approved schema defining its table name, columns, data types, grouping level, and constraints before implementation.

## 6.2 Naming Convention

| Object | Convention | Example | Status |
|---|---|---|---|
| Atomic output file | Lowercase `snake_case` of the entity, no prefix | `residents.csv`, `resident_chronic_conditions.csv` | In use |
| Atomic output column | Lowercase `snake_case`; preserve natural key names | `resident_id`, `risk_level` | In use |
| Primary key | `<entity>_id` | `resident_id`, `schedule_id` | In use |
| Foreign key | Same name as the referenced primary key | `resident_id`, `purok_id` | In use |
| Reference file | `reference/<entity>.csv` | `reference/residents.csv` | In use |
| Quarantine table | `<batch_id>_quarantine.csv` | `BATCH_3d209da2_quarantine.csv` | In use |
| Dimension table | `dim_<entity>` (reserved) | `dim_residents` | Reserved; requires approved schema |
| Fact table | `fact_<process>` (reserved) | `fact_schedules` | Reserved; requires approved schema |
| Surrogate key | `<entity>_key` in the dimensional layer only | `resident_key` | Reserved; not generated in this stage |
| Derived measure | Descriptive `<measure>` such as `condition_count` | `condition_count` | Reserved; requires approved schema |

The `dim_` and `fact_` prefixes and `_key` surrogate keys are defined here so a future dimensional layer has a fixed convention. They are deliberately **not** used now because the approved contract is the atomic layer and the Data Loading Stage owns any dimensional model. If the dimensional layer is approved later, every `dim_`/`fact_` table must also define its grain, surrogate-key generation, and source-to-target mapping.

## 6.3 Source-to-Target Mapping

This mapping differs from the Stage 1 extraction contract: Stage 1 preserves source values and types, while Stage 2 converts types, standardizes codes, applies the deterministic duplicate survivor, and drops extraction-window columns that are not part of the analytical output.

| Stage 1 source | Stage 2 target | Target type | Rules applied | Difference from extraction contract |
|---|---|---|---|---|
| `residents.resident_id` | `residents.resident_id` | 64-bit integer | C-01, C-03, S-04 | Text → integer; duplicate survivor applied |
| `residents.purok_id` | `residents.purok_id` | 64-bit integer | C-01, C-05, S-04 | Text → integer; approved parent reference required |
| `residents.risk_level` | `residents.risk_level` | Text code | C-02, S-03, S-05 | Free text → approved four-value code |
| `residents.created_at`, `residents.updated_at` | Not carried forward | — | — | Extraction-window columns dropped from output |
| `resident_chronic_conditions.condition_id` | `resident_chronic_conditions.condition_id` | 64-bit integer | C-01, C-03, S-04 | Text → integer; duplicate survivor applied |
| `resident_chronic_conditions.resident_id` | `resident_chronic_conditions.resident_id` | 64-bit integer | C-01, C-05, S-04 | Text → integer; approved parent reference required |
| `resident_chronic_conditions.condition_name` | `resident_chronic_conditions.condition_name` | Text | C-02, C-04, C-06, S-07 | Embedded document reduced to its `name` member; Title Case |
| `resident_chronic_conditions.created_at` | `resident_chronic_conditions.created_at` | ISO 8601 UTC timestamp | C-01, S-02 | Normalized to UTC with microseconds preserved |
| `resident_chronic_conditions.updated_at` | Not carried forward | — | — | Extraction-window column dropped from output |
| `schedules.schedule_id` | `schedules.schedule_id` | 64-bit integer | C-01, C-03, S-04 | Text → integer; duplicate survivor applied |
| `schedules.resident_id` | `schedules.resident_id` | 64-bit integer | C-01, C-05, S-04 | Text → integer; approved parent reference required |
| `schedules.date` | `schedules.date` | ISO 8601 date | C-01, S-01 | Normalized date, no time component |
| `schedules.status` | `schedules.status` | Text code | C-02, S-03, S-06 | Free text → `COMPLETED`, `MISSED`, or `CANCELLED` |
| `schedules.updated_at`, `schedules.created_at` | Not carried forward | — | — | Extraction-window columns dropped from output |
| `puroks.purok_id` | `puroks.purok_id` | 64-bit integer | C-01, C-03, S-04 | Text → integer; duplicate survivor applied |
| `puroks.name` | `puroks.name` | Text | C-01, C-02, C-03, C-06, S-03 | Trimmed and Title Case; non-alphabetic names quarantined |
| `puroks.created_at`, `puroks.updated_at` | Not carried forward | — | — | Extraction-window columns dropped from output |

## 6.4 Schema Consistency

The transformation process must compare incoming column names and expected data types with the approved input contract.

- **Missing required columns:** Stop the affected batch and log the schema error.
- **Unexpected columns:** Flag for review rather than silently including them.
- **Changed data types or incompatible formats:** Stop or quarantine affected data according to severity.
- **Approved schema changes:** Update the transformation contract and version the corresponding rules.

# 7. Transformation Validation and Data Quality Checks

Validation verifies the correctness, completeness, consistency, and business-rule compliance of the transformed data.

| Check ID | Check name | Target | Purpose | Measurable PASS criteria | Severity |
|---|---|---|---|---|---|
| V-01 | Record reconciliation | Each input and output dataset, and the batch total | Detect missing or unaccounted-for records | For every dataset and for the batch: `records_read = records_output + records_rejected + records_duplicates_excluded` | Critical |
| V-02 | Required fields | Required columns in all four outputs | Prevent missing mandatory values | Blank-value count = 0 in every required output column | Critical |
| V-03 | Primary-key uniqueness | `resident_id`, `condition_id`, `schedule_id`, `purok_id` | Prevent duplicate keys | Duplicate primary-key count = 0 in every output table | Critical |
| V-04 | Referential integrity | Resident, purok, condition, and schedule relationships | Prevent orphan references | Orphan count = 0 against the approved parent dataset plus `reference/` parents | Critical |
| V-05 | Type and format conformance | Identifiers, dates, timestamps, text domains | Ensure expected output formats | Format-error count = 0: every identifier is an integer, every date matches `YYYY-MM-DD`, every timestamp matches ISO 8601 UTC, and every code is approved | Critical |
| V-06 | Join cardinality | B-01 resident–purok join and child–parent joins | Detect unintended row multiplication | `unmatched = 0`, `multiple_matches = 0`, `row_multiplication = 0`, and parent keys unique | Critical |
| V-07 | Aggregation reconciliation | Derived summaries | Ensure totals represent the contributing records | Aggregates reconcile with eligible input records; passes as not applicable when no derived output is approved | Critical |
| V-08 | Business-rule validation | Risk levels, statuses, cancelled-schedule handling, and derived outputs | Ensure approved business rules are followed | Count of values outside the approved mapping or B-rules = 0 | Critical |
| V-09 | Rejection-rate monitoring | Each dataset and the batch | Monitor transformation quality | Overall `rejection_rate = records_rejected / records_read × 100 ≤ 5.00%` | Critical (warning routing) |
| V-10 | Transformation warning review | Non-critical data-quality findings | Identify issues that need attention | Every warning is documented and assigned for review; unresolved warnings = 0 | Non-critical |

### Reconciliation Rules

- A record that is cleaned and retained counts as output, not rejected.
- `records_modified` is tracked separately and is not part of the reconciliation equation.
- Superseded duplicate records are counted in `records_duplicates_excluded`, not in `records_rejected`, and are included in the reconciliation equation.
- For aggregations, reconcile contributing input records and measures, not only output row counts.
- For joins, validate unmatched records and unexpected row multiplication.
- For business exclusions, record the excluded count and reason.
- No record may be silently dropped: every input row ends as output, rejected, or a documented duplicate exclusion.

# 8. Transformation Metadata and Log Specification

The transformation process must create metadata and logs for every batch run.

## 8.1 Required Metadata

| Field | Purpose | Example or format |
|---|---|---|
| `run_id` | Unique transformation run identifier | `CITICARE_TRANS_20261114_3d209da2` |
| `parent_run_id` | Reference to the extraction run that produced the input | `CITICARE_EXT_20261114_3d209da2` |
| `batch_id` | Identifies the processed batch; derived deterministically from the parent run | `BATCH_3d209da2` |
| `batch_window` | Identifies the extraction period recorded in the handover | `FULL LOAD 2026-11-14` or `2026-09-01 to 2026-09-30` |
| `file_name` | Identifies the processed dataset | `residents.csv` |
| `start_timestamp` | Transformation start time | ISO 8601 UTC timestamp |
| `end_timestamp` | Transformation end time | ISO 8601 UTC timestamp |
| `status` | Final batch status | `SUCCESS`, `WARNING`, `FAILED` |
| `records_read` | Number of input records received per dataset | Actual count |
| `records_output` | Number of retained output records per dataset | Actual count |
| `records_rejected` | Number of rejected or quarantined records per dataset | Actual count |
| `records_duplicates_excluded` | Number of superseded duplicate records per dataset | Actual count |
| `records_business_excluded` | Rejected plus duplicate-excluded records excluded from business outputs | `2` |
| `records_modified` | Number of retained records modified by a cleaning or standardization rule | Actual count |
| `overall_rejection_rate` | `records_rejected / records_read`, as a decimal and percentage | `0.0339` (3.39%) |
| `rejection_rate_threshold` | Approved maximum rejection rate applied by V-09 | `0.05` (5.00%) |
| `rules_applied` | Counts of records affected by each rule that fired | `S-05: 14`, `S-06: 29` |
| `rule_trace` | Per fired rule, the profiled issue IDs it treats and the affected record count | `C-01: [P-01, P-02, ...], records: 2` |
| `decision` | Acceptance decision | `APPROVED`, `MANUAL REVIEW`, `REJECTED` |
| `handover_status` | Handover state | `APPROVED`, `HELD`, `REJECTED` |
| `reference_parent_counts` | Approved parent keys available for referential checks | `puroks: 6`, `residents: 14` |
| `validation_results` | Results of quality checks by check ID | `V-01: PASS` |
| `error_code` | Identifies an error when applicable | `SCHEMA_MISSING_COLUMN` |
| `error_message` | Describes the processing failure | Concise error description |
| `duration_seconds` | Measures transformation duration | Actual elapsed seconds |
| `code_version` | Identifies the transformation code version | `TRN-2.1.0` |
| `rules_version` | Identifies the rule set version | `RULES-2.0.0` |
| `files` | Per-file evidence: file name, read, output, rejected, modified, validation results | One entry per dataset |

These fields are written to `metadata.json`, `manifest.json`, and the audit copy under `logs/audit/<year>/`. Actual execution values are recorded by the pipeline; the examples are illustrative only.

## 8.2 Logging Uses

- **Monitoring:** Track batch status, processing duration, record counts, and validation results.
- **Troubleshooting:** Identify failed conversions, duplicate identifiers, orphan relationships, and schema changes.
- **Auditing:** Trace transformed outputs to the extraction run, batch window, and code/rule versions.
- **Data lineage:** Identify the inputs and transformation rules that produced each output.
- **Recovery:** Locate a failed batch and rerun it using the same batch identity.
- **Privacy:** Avoid recording unnecessary resident or health information in operational logs.

# 9. Log Retention, Rejected Data, and Access

## 9.1 Retention and Storage

| Item | Specification |
|---|---|
| Transformation log retention | 12 months, aligned with the documented operational extraction-log retention, subject to approved organizational policy |
| Log location | Secured ETL environment, in a dedicated `logs` directory |
| Quarantine location | Restricted-access `Data_Pipelines/Transformation/quarantine/` directory, one file per batch: `<batch_id>_quarantine.csv` |
| Quarantine contents | Batch ID, run IDs, source file/table/key, rule ID, column, raw value, reason code, reason, and quarantine timestamp |
| Operational logs | Used for monitoring, troubleshooting, and batch recovery |
| Audit records | Preserve run identifiers, batch windows, versions, outcomes, and lineage; retain longer if required by approved policy |
| Archiving | Archive records when required while preserving their traceability and accessibility during the retention period |
| Deletion | Only authorized personnel may delete records after the approved retention period and when no audit, troubleshooting, or recovery need remains |

## 9.2 Access Permissions

| Role | Permissions |
|---|---|
| Transformation service account | Write operational logs and quarantine records |
| Authorized developers and maintainers | Read logs and investigate failures; modify configuration and rules as authorized |
| System administrators | Manage storage, permissions, archiving, and approved deletion |
| Designated reviewers or auditors | Read relevant records for approved review and audit purposes |

Rejected records must not be deleted before the defined retention period or while required for investigation, correction, audit, or recovery. Access to quarantine records must be restricted because the datasets may contain sensitive health information.

## 9.3 Quarantine Table Schema

Every rejected or superseded record is written to the batch quarantine table. The table is the authoritative record of rejection; a rejection that is not in quarantine is a pipeline defect.

| Column | Type | Required | Purpose |
|---|---|---|---|
| `batch_id` | Text | Yes | Batch that produced the rejection |
| `run_id` | Text | Yes | Transformation run that produced the rejection |
| `parent_run_id` | Text | Yes | Extraction run that supplied the input |
| `source_file` | Text | Yes | Input CSV file, such as `residents.csv` |
| `source_table` | Text | Yes | Logical dataset, such as `residents` |
| `source_pk` | Text | Yes | Primary-key value of the rejected record, where available |
| `rule_id` | Text | Yes | Rule that rejected the record, such as `C-05`, `S-02`, or `C-03` |
| `column_name` | Text | Yes | Column that triggered the rejection |
| `raw_value` | Text | Yes | Raw value, truncated to 200 characters |
| `reason_code` | Text | Yes | Stable code, such as `ORPHAN_FOREIGN_KEY` or `INVALID_DATE` |
| `reason` | Text | Yes | Human-readable explanation |
| `quarantined_at` | ISO 8601 UTC timestamp | Yes | Time the record was quarantined |

Quarantine rules:

- Each rejected record produces exactly one quarantine row per failed rule.
- `records_rejected` equals the number of records rejected by C-01, C-04, C-05, C-06, S-01, S-02, S-04, S-05, and S-06.
- Superseded duplicates from C-03 are also quarantined, but are counted separately in `records_duplicates_excluded` to avoid double counting.
- The quarantine row count is recorded in `metadata.json`, `manifest.json`, `transform.log`, and the handover summary.
- No raw record is placed in an operational log; `raw_value` is limited to the failing field and truncated.

# 10. Transformation Acceptance and Handover Rules

The Data Transformation process determines whether its output can proceed to the Data Loading Stage.

## 10.1 Rejection-Rate Threshold

The approved maximum rejection rate for a transformation batch is **5.00%** (`0.05`), applied by check V-09 and configurable only through `CITICARE_TRN_REJECTION_RATE_LIMIT`.

Justification for 5.00%:

- The measured baseline is 2 rejected records out of 59 (3.39%) for batch `BATCH_3d209da2`, so the threshold leaves limited headroom for normal data-entry noise.
- It blocks a batch in which more than 1 in 20 input records cannot be transformed, which indicates a source or rule problem rather than isolated errors.
- It is low enough to protect the curated layer, while not failing a batch for one or two genuinely bad records.
- Changing the threshold requires a documented configuration change and a new `rules_version`; it cannot be changed silently during a run.

The rejection rate is calculated as:

`rejection_rate = records_rejected / records_read × 100`

Duplicate exclusions are reported separately as `records_duplicates_excluded` and are not added to `records_rejected`. Business exclusions (B-05) are the sum of rejected and duplicate-excluded records. Per-dataset rates are recorded for diagnosis, but the acceptance decision uses the overall batch rate.

## 10.2 Decision Rules

| Condition | Acceptance decision | Pipeline action | Approval type |
|---|---|---|---|
| All critical checks pass, no unresolved critical issues exist, and the rejection rate is within the approved threshold | `APPROVED` | Package outputs and hand over to the Data Loading Stage | Automatic |
| Non-critical warnings exist or the rejection rate exceeds the approved threshold | `MANUAL REVIEW` | Hold the batch for investigation and authorized approval | Manual |
| Any critical validation fails or required schema/relationship checks cannot be completed | `REJECTED` | Stop handover; correct the issue and rerun or quarantine affected data | Automatic stop |
| Processing cannot complete due to an execution error | `FAILED` | Preserve inputs and logs, correct the cause, and rerun the batch | Recovery procedure |

The responsible project owner or designated data-quality reviewer must approve manual-review cases. A batch must not proceed merely because its rejection rate is low if any critical validation has failed.

## 10.3 Handover Requirements

The handover package must contain:

- Approved transformed CSV files.
- Transformation run ID and parent extraction run ID.
- Batch ID and batch window.
- Record counts, including output, rejected, modified, and documented exclusions.
- Validation results and the overall acceptance decision.
- Transformation code and rules versions.
- Quarantine references and rejection reasons, stored securely.
- Any approved business summaries and their output schema.

The Data Transformation process prepares the data for loading but does not perform the final database or warehouse load.

# 11. Common Transformation Problems and Mitigation

| Problem | Possible cause | Impact | Mitigation |
|---|---|---|---|
| Duplicate records after a rerun | Batch output appended without idempotent handling | Duplicate residents, schedules, or condition records | Use deterministic processing and replace or rebuild output for the same batch ID. |
| Missing parent record in a monthly batch | Parent record is not included in the current incremental extraction | Valid relationships may be incorrectly treated as orphans | Validate against an approved parent reference dataset or previously validated state. |
| Invalid date or timestamp | Unexpected format or malformed value in the CSV | Schedule dates or condition timestamps cannot be processed reliably | Apply documented conversion rules; quarantine and log failures. |
| Unexpected schema change | Required column removed, renamed, or changed | Transformation may fail or produce incorrect output | Compare the input schema with the contract and stop affected processing until reviewed. |
| Duplicate primary keys | Repeated identifiers in the extracted data | Invalid output keys and potential double counting | Detect duplicates, apply only approved resolution rules, and quarantine unresolved conflicts. |
| Unrecognized risk or schedule status | Value not covered by the approved mapping | Inconsistent reporting or unsupported classifications | Preserve traceability, flag the value, and obtain an approved mapping before proceeding. |
| Join row multiplication | Reference keys are not unique or the join is incorrectly defined | Inflated counts and misleading summaries | Validate key uniqueness and join cardinality before accepting output. |
| Missing reference data | Required parent or lookup dataset is unavailable | Referential integrity cannot be verified | Hold affected records and report the unresolved dependency. |
| Excessive rejected records | Widespread invalid values or a source-data change | Batch may fail acceptance criteria | Investigate the cause, quantify affected records, correct approved rules or input issues, and rerun. |
| Sensitive information exposed in logs | Full record contents written to error messages | Unnecessary disclosure of resident information | Log record identifiers and reason codes where possible; restrict access to quarantine files. |
| Incorrect aggregate totals | Wrong grouping, status mapping, or filtering | Misleading health and consultation reports | Reconcile aggregates against eligible input records and stop handover when differences remain unexplained. |