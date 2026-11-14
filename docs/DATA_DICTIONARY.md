# Data Dictionary

**Pending discovery.** No sample files have been supplied yet. All 8 dataset categories in `config/datasets.yaml` have `schema_status: PENDING_DISCOVERY` and empty column lists. This is deliberate: source column names must not be guessed.

For each sample file, record here:

| Dataset | Column (as in file) | Type | Nullable | Example (synthetic) | Maps to contract field | Notes |
|---|---|---|---|---|---|---|

Then set `required_columns`, `primary_key_columns` and `date_column`, and switch `schema_status: DEFINED`.
