"""REST API (FastAPI). Thin HTTP layer over the core modules.

The automation itself (ingestion, processing, reporting) runs headless through the
CLI/scheduler and the domain packages; this API exposes it to the React UI today and
to the APIS intranet in future.
"""
