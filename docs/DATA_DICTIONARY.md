# Data Dictionary

**Pending discovery.** No sample files have been supplied yet. All 8 dataset categories in `config/datasets.yaml` have `schema_status: PENDING_DISCOVERY` and empty column lists. This is deliberate: source column names must not be guessed.

For each sample file, record here:

| Dataset | Column (as in file) | Type | Nullable | Example (synthetic) | Maps to contract field | Notes |
|---|---|---|---|---|---|---|

Then set `required_columns`, `primary_key_columns` and `date_column`, and switch `schema_status: DEFINED`.

## How schemas are defined (v0.4.0)

1. Dataset Registry -> choose the dataset -> **Define** -> upload a real sample file.
2. The app reads the file's own columns and sample values (nothing is assumed).
3. Map each column to an internal field (`ingestion/schema_definition.py` lists them per dataset), choose the business key, date formats, and value maps (e.g. source status `P` -> PRESENT).
4. Save. Each save is a new version; earlier uploads keep the version they used.

Synthetic schemas used by the demo and tests live in `demo/synthetic.py` and are **not** real column names.
