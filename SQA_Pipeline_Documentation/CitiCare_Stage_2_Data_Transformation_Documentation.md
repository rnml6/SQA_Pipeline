# Stage 2: Data Transformation Documentation

## Objective

The objective of the Data Transformation process is to clean, standardize, validate, and prepare the extracted CitiCare datasets for the Data Loading Stage. All transformations must be documented, traceable, and validated before the transformed data is handed over for loading.

# 1. Transformation Input and Processing Specification

## 1.1 Input Source

The Data Transformation process receives the approved CSV files and extraction metadata from the Extraction Stage.

| Item | Specification |
|---|---|
| Input source | Approved extraction handover |
| Input files | `residents.csv`, `resident_chronic_conditions.csv`, `schedules.csv`, `puroks.csv` |
| Format | CSV |
| Location | Approved extraction staging directory; exact path to be configured |
| Extraction Run ID | Retrieved from the extraction handover as `parent_run_id` |
| Batch window | Monthly extraction window supplied by the Extraction Stage |
| Required metadata | Extraction run ID, batch window, input filenames, record counts, and extraction validation status |

The Data Transformation process must use the received extraction output and must not re-extract data from the source system. The actual extraction run ID and batch window must be recorded from the handover.

## 1.2 Batch Processing Method

| Item | Specification |
|---|---|
| Transformation tool | Python |
| Supporting modules | `csv`, `datetime`, `sqlite3`, `logging` |
| Processing method | Monthly batch processing |
| Schedule | Monthly, aligned with the approved extraction schedule |
| Batch size | All approved records included in the extraction handover |
| Output | Transformed CSV datasets, validation results, metadata, and rejected-record files |
| Failure recovery | Record the error, preserve the input, correct the problem, and rerun the same batch |
| Idempotency | Required; reruns must not create duplicate output records |

The transformation process must use deterministic rules and controlled output replacement or rebuilding for the same batch. Database loading is handled by the Data Loading Stage.

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
3. Clean and standardize `puroks.csv` and `residents.csv`.
4. Clean and standardize `resident_chronic_conditions.csv` and `schedules.csv`.
5. Validate primary keys, foreign keys, and cross-file relationships.
6. Apply approved business transformation rules.
7. Validate and reconcile transformed outputs.
8. Package approved outputs and metadata for the Data Loading Stage.

### Dependencies and Assumptions

- The Extraction Stage provides the approved files, extraction run ID, batch window, record counts, and validation status.
- The datasets follow the documented extraction schema.
- The monthly batch window is determined by the extraction handover.
- Relationship checks require an approved reference dataset or previously validated parent records when monthly incremental files do not contain every referenced record.
- Late-arriving records are processed through a subsequent or explicitly rerun extraction handover.
- Missing lookup data and unresolved relationships must be reported and must not be silently ignored.
- Clinical classifications and allowed `risk_level` or `status` values must follow approved CitiCare definitions.
- Actual directory paths, code versions, and execution timestamps must be recorded during implementation.

# 2. Data Profiling and Issue Identification

Profiling must be performed before cleaning. Actual issue counts and percentages must be obtained by running the profiling process against the received CSV files. The examples below are potential issues to investigate, not confirmed findings.

| File and column | Issue type | Example | Affected records | Planned treatment |
|---|---|---|---|---|
| `residents.csv`: `resident_id` | Missing or duplicate identifier | Blank value or repeated ID | To be measured | Required-field and duplicate handling rules |
| `residents.csv`: `purok_id` | Missing or unmatched reference | ID not found in approved purok reference data | To be measured | Orphan relationship handling rule |
| `residents.csv`: `risk_level` | Inconsistent text or unrecognized value | `" high "` | To be measured | Text cleaning and approved value mapping |
| `resident_chronic_conditions.csv`: `condition_id` | Missing or duplicate identifier | Blank value or repeated ID | To be measured | Required-field and duplicate handling rules |
| `resident_chronic_conditions.csv`: `resident_id` | Orphan relationship | Resident ID not found in approved resident records | To be measured | Orphan relationship handling rule |
| `resident_chronic_conditions.csv`: `condition_name` | Whitespace or inconsistent casing | `" hypertension "` | To be measured | Text cleaning and standardization rules |
| `resident_chronic_conditions.csv`: `created_at` | Invalid timestamp format | Unparseable date/time string | To be measured | Timestamp conversion rule |
| `schedules.csv`: `schedule_id` | Missing or duplicate identifier | Blank value or repeated ID | To be measured | Required-field and duplicate handling rules |
| `schedules.csv`: `resident_id` | Orphan relationship | Resident ID not found in approved resident records | To be measured | Orphan relationship handling rule |
| `schedules.csv`: `date` | Invalid or inconsistent date | Unparseable date string | To be measured | Date conversion rule |
| `schedules.csv`: `status` | Inconsistent or unrecognized value | `" completed "` | To be measured | Text cleaning and approved status mapping |
| `puroks.csv`: `purok_id` | Missing or duplicate identifier | Blank value or repeated ID | To be measured | Required-field and duplicate handling rules |
| `puroks.csv`: `name` | Leading/trailing whitespace or missing value | `" Purok 1 "` | To be measured | Missing-value and text cleaning rules |

For every identified issue, record the measured count, percentage, sample values, and applicable cleaning, standardization, or business rule. Do not report an issue as present or absent until profiling has been executed.

# 3. Data Cleaning Rules

The following rules define how identified data-quality issues are handled. Their application and record counts must be captured in the transformation logs.

| Rule ID | Target | Condition | Action | Justification |
|---|---|---|---|---|
| C-01: Required values | Required columns in all four files | Required identifier or field is missing | Reject the affected record to quarantine and log the reason. | Prevents incomplete records from entering the transformed output. |
| C-02: Whitespace cleanup | Text fields in all four files | Leading or trailing whitespace exists | Trim leading and trailing whitespace and log the rule application. | Prevents inconsistent matching and formatting. |
| C-03: Duplicate identifiers | `resident_id`, `condition_id`, `schedule_id`, `purok_id` | Duplicate primary key exists | Retain a record only when a deterministic, approved rule identifies the authoritative record; otherwise quarantine the conflicting records for review. | Prevents duplicate keys and unintended record loss. |
| C-04: Invalid values | `risk_level`, `status`, `condition_name`, and other validated fields | Value violates an approved domain or business rule | Reject or quarantine the record with the relevant rule ID and reason. | Prevents unsupported values from entering the output. |
| C-05: Orphan relationships | `residents.purok_id`, `resident_chronic_conditions.resident_id`, `schedules.resident_id` | Referenced parent cannot be found in the approved reference set | Quarantine the affected record and log the missing reference. | Preserves referential integrity without silently dropping data. |
| C-06: Invalid characters | Text fields | Characters violate an explicitly approved field rule | Remove or correct only the characters specified by the rule; otherwise quarantine for review. | Avoids damaging valid names or descriptions through indiscriminate character removal. |

### Duplicate Handling

- Primary-key duplicates must be identified before output generation.
- A record must not be selected as the winner based on an unsupported assumption.
- Where no authoritative record can be identified, conflicting records must be quarantined for review.
- Every rejected record must include its batch ID, rule ID, source file, and rejection reason.

### Record Handling

Missing values must not be replaced with arbitrary defaults. Invalid or out-of-range values must be handled according to approved field-specific rules. Records that are cleaned and retained count as modified, not rejected.

# 4. Standardization and Data Type Rules

## 4.1 Data Types and Formats

| Rule ID | Column | Source type | Target type or format | On failure |
|---|---|---|---|---|
| S-01 | `schedules.date` | CSV text representing a date | ISO 8601 date, `YYYY-MM-DD` | Reject and log |
| S-02 | `resident_chronic_conditions.created_at` | CSV text representing a timestamp | ISO 8601 timestamp | Reject and log |
| S-03 | `risk_level`, `status`, `condition_name`, `puroks.name` | Text | Trimmed, consistently formatted text | Quarantine unrecognized values when an approved domain is required |
| S-04 | `resident_id`, `purok_id`, `condition_id`, `schedule_id` | CSV text representation of identifiers | Integer-compatible identifier | Reject and log if conversion fails |

Date and timestamp values must not be converted using ambiguous locale assumptions. A timezone must be applied only when defined by the source contract or approved business rules.

## 4.2 Reference Values and Codes

| Rule ID | Field | Standardization rule | On failure |
|---|---|---|---|
| S-05 | `risk_level` | Apply only the approved CitiCare risk-level mapping. | Quarantine or flag for review if unrecognized. |
| S-06 | `schedules.status` | Apply only the approved schedule-status mapping. | Quarantine or flag for review if unrecognized. |
| S-07 | `condition_name` | Trim whitespace and apply an approved naming convention without changing the meaning of the condition. | Flag unresolved values for review. |

No new clinical risk categories, schedule statuses, or medical classifications may be invented.

## 4.3 Numeric Precision

The documented input fields are identifiers, text, dates, and timestamps. No numeric business measure requiring decimal precision or rounding is currently specified. If such a field is added, its precision and rounding rule must be documented before implementation.

# 5. Business Transformation Rules

The Data Transformation process prepares cleaned records for resident, chronic-condition, schedule, and purok-level analysis.

| Rule ID | Input columns | Logic | Output column or dataset | Business reason |
|---|---|---|---|---|
| B-01 | `residents.resident_id`, `residents.purok_id`, `puroks.purok_id`, `puroks.name` | Join residents to the approved purok reference using `purok_id`. | Resident records enriched with approved purok information, if required by the output contract | Supports resident and purok-level analysis. |
| B-02 | `resident_chronic_conditions.resident_id`, `resident_chronic_conditions.condition_id` | Group valid relationship records by resident and count condition records when required. | Resident chronic-condition count | Supports chronic-condition summaries. |
| B-03 | `schedules.resident_id`, `schedules.status`, `schedules.date` | Group valid schedule records by approved status and date when required. | Schedule or consultation summary | Supports consultation follow-up and trend reporting. |
| B-04 | `residents.purok_id`, `puroks.name`, validated analytical measures | Group approved resident or health measures by purok. | Purok-level summary | Supports community-level reporting. |
| B-05 | All datasets and their validation results | Exclude records that fail mandatory transformation rules from business-ready outputs, while preserving them in quarantine with a reason. | Validated output and quarantine records | Prevents invalid records from contaminating reports while preserving traceability. |

### Join and Aggregation Requirements

- Use the documented keys: `residents.purok_id` references `puroks.purok_id`; `resident_chronic_conditions.resident_id` and `schedules.resident_id` reference `residents.resident_id`.
- Validate join cardinality to prevent unexpected row multiplication.
- Unmatched records must be counted and quarantined or held for review.
- Aggregations must use validated records and documented grouping levels.
- Since extraction is monthly, a summary based only on the current batch must be identified as batch-scoped. Complete historical summaries require an approved historical dataset or prior validated state.
- No clinical score, diagnosis, or risk classification may be derived unless an approved business rule defines the logic.
- Every business exclusion must be counted, logged, and assigned a reason.

# 6. Transformed Data Contract and Naming Convention

## 6.1 Required Output Schema

The transformed output retains the documented identifiers and fields unless an approved business transformation explicitly adds an output field.

| Output file | Column | Target type | Nullability and constraints |
|---|---|---|---|
| `residents.csv` | `resident_id` | Integer-compatible | Required, unique primary key |
| `residents.csv` | `purok_id` | Integer-compatible | Required foreign key |
| `residents.csv` | `risk_level` | Text | Required; value must follow approved mapping |
| `resident_chronic_conditions.csv` | `condition_id` | Integer-compatible | Required, unique primary key |
| `resident_chronic_conditions.csv` | `resident_id` | Integer-compatible | Required foreign key |
| `resident_chronic_conditions.csv` | `condition_name` | Text | Required |
| `resident_chronic_conditions.csv` | `created_at` | ISO 8601 timestamp | Required |
| `schedules.csv` | `schedule_id` | Integer-compatible | Required, unique primary key |
| `schedules.csv` | `resident_id` | Integer-compatible | Required foreign key |
| `schedules.csv` | `date` | ISO 8601 date | Required |
| `schedules.csv` | `status` | Text | Required; value must follow approved mapping |
| `puroks.csv` | `purok_id` | Integer-compatible | Required, unique primary key |
| `puroks.csv` | `name` | Text | Required |

Any derived summary output must have a separately approved schema defining its columns, data types, grouping level, and constraints before implementation.

## 6.2 Naming Convention

- Use lowercase `snake_case` for file names and columns.
- Preserve the documented identifier names, including `resident_id`, `condition_id`, `schedule_id`, and `purok_id`.
- Use descriptive names for derived fields, such as `condition_count`, only when approved in the output contract.
- Use prefixes such as `dim_` and `fact_` only if dimensional tables are explicitly included in the approved transformation design.
- Do not generate surrogate keys unless required by the approved target data model.

## 6.3 Source-to-Target Mapping

| Source column | Target column | Transformation |
|---|---|---|
| `residents.resident_id` | `residents.resident_id` | Validate identifier and uniqueness using the required-value, duplicate, and type-conversion rules |
| `residents.purok_id` | `residents.purok_id` | Validate type and reference using the orphan relationship rule |
| `residents.risk_level` | `residents.risk_level` | Apply approved value mapping |
| `resident_chronic_conditions.condition_id` | `resident_chronic_conditions.condition_id` | Validate identifier and uniqueness |
| `resident_chronic_conditions.resident_id` | `resident_chronic_conditions.resident_id` | Validate type and resident reference |
| `resident_chronic_conditions.condition_name` | `resident_chronic_conditions.condition_name` | Trim whitespace and standardize approved text format |
| `resident_chronic_conditions.created_at` | `resident_chronic_conditions.created_at` | Standardize timestamp |
| `schedules.schedule_id` | `schedules.schedule_id` | Validate identifier and uniqueness |
| `schedules.resident_id` | `schedules.resident_id` | Validate type and resident reference |
| `schedules.date` | `schedules.date` | Standardize date format |
| `schedules.status` | `schedules.status` | Apply approved status mapping |
| `puroks.purok_id` | `puroks.purok_id` | Validate identifier and uniqueness |
| `puroks.name` | `puroks.name` | Trim whitespace and standardize text |

## 6.4 Schema Consistency

The transformation process must compare incoming column names and expected data types with the approved input contract.

- **Missing required columns:** Stop the affected batch and log the schema error.
- **Unexpected columns:** Flag for review rather than silently including them.
- **Changed data types or incompatible formats:** Stop or quarantine affected data according to severity.
- **Approved schema changes:** Update the transformation contract and version the corresponding rules.

# 7. Transformation Validation and Data Quality Checks

Validation verifies the correctness, completeness, consistency, and business-rule compliance of the transformed data.

| Check name | Target | Purpose | Validation criteria | Severity |
|---|---|---|---|---|
| Record reconciliation | Each input and output dataset | Detect missing or unaccounted-for records | `records_read = records_output + records_rejected + documented_duplicate_exclusions` | Critical |
| Required fields | Required columns in all four outputs | Prevent missing mandatory values | No null or blank values in required fields | Critical |
| Primary-key uniqueness | `resident_id`, `condition_id`, `schedule_id`, `purok_id` | Prevent duplicate keys | Duplicate primary-key count = 0 | Critical |
| Referential integrity | Resident, purok, condition, and schedule relationships | Prevent orphan references | All required references match the approved parent dataset | Critical |
| Type and format conformance | Identifiers, dates, timestamps, text domains | Ensure expected output formats | All retained values conform to the output contract | Critical |
| Join cardinality | Business transformation joins | Detect unintended row multiplication | Output row counts and key multiplicities match the approved join design | Critical |
| Aggregation reconciliation | Derived summaries | Ensure totals represent the contributing records | Aggregated counts and measures reconcile with eligible input records | Critical |
| Business-rule validation | Risk levels, statuses, and derived outputs | Ensure approved business rules are followed | All retained values and derived results meet approved rules | Critical |
| Rejection-rate monitoring | Each dataset and batch | Monitor transformation quality | Rejection rate is within the project-approved threshold | Critical |
| Transformation warning review | Non-critical data-quality findings | Identify issues that need attention | Warnings are documented and assigned for review | Non-critical |

### Reconciliation Rules

- A record that is cleaned and retained counts as output, not rejected.
- `records_modified` is tracked separately and is not part of the reconciliation equation.
- Explicitly documented duplicate exclusions must be counted separately and included in reconciliation.
- For aggregations, reconcile contributing input records and measures, not only output row counts.
- For joins, validate unmatched records and unexpected row multiplication.
- For business exclusions, record the excluded count and reason.
- No record may be silently dropped.

# 8. Transformation Metadata and Log Specification

The transformation process must create metadata and logs for every batch run.

## 8.1 Required Metadata

| Field | Purpose | Example or format |
|---|---|---|
| `run_id` | Unique transformation run identifier | `CITICARE_TRANS_20261001_001` |
| `parent_run_id` | Reference to the extraction run | Actual extraction run ID |
| `batch_id` | Identifies the processed batch | `BATCH_20261001_001` |
| `batch_window` | Identifies the extraction period | Actual monthly date range |
| `file_name` | Identifies the processed dataset | `residents.csv` |
| `start_timestamp` | Transformation start time | ISO 8601 timestamp |
| `end_timestamp` | Transformation end time | ISO 8601 timestamp |
| `status` | Final batch result | `SUCCESS`, `WARNING`, `FAILED` |
| `records_read` | Number of input records processed | Actual count |
| `records_output` | Number of retained output records | Actual count |
| `records_rejected` | Number of rejected or quarantined records | Actual count |
| `records_modified` | Number of retained records modified | Actual count |
| `rules_applied` | Counts of records affected by each rule | `C-02: actual_count` |
| `validation_results` | Results of quality checks | Check name and result |
| `error_code` | Identifies an error when applicable | Approved error code |
| `error_message` | Describes the processing failure | Concise error description |
| `duration_seconds` | Measures transformation duration | Actual elapsed seconds |
| `code_version` | Identifies the transformation code version | Version identifier |
| `rules_version` | Identifies the rule set version | Version identifier |

Example run IDs and values are illustrative. Actual execution values must be recorded by the pipeline.

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
| Quarantine location | Restricted-access `quarantine` directory organized by batch and dataset |
| Quarantine contents | Minimum necessary record data or record reference, source file, batch ID, rule ID, rejection reason, and timestamp |
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

# 10. Transformation Acceptance and Handover Rules

The Data Transformation process determines whether its output can proceed to the Data Loading Stage.

## 10.1 Rejection-Rate Threshold

The project must approve the maximum permitted rejection rate before production processing begins. The numeric threshold is not specified in the available documentation and must be formally defined before production approval.

The rejection rate is calculated as:

`rejection_rate = records_rejected / records_read × 100`

The calculation must follow the approved treatment of documented duplicate exclusions and business exclusions. The reporting method must clearly distinguish rejected records from records deliberately excluded by approved business rules.

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