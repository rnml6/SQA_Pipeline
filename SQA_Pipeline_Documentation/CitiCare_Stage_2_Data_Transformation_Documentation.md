# Stage 2: Data Transformation Documentation

## Objective

The objective of the Data Transformation process is to clean, standardize, validate, and prepare the extracted CitiCare datasets for the Data Loading Stage. All transformations must be documented, traceable, and validated before the transformed data is handed over for loading.

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