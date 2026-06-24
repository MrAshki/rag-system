# Temporary backward-compatible shim. The real implementation moved to
# document_pipeline/ingest.py. New code should import from document_pipeline
# directly; this file exists only so old `import ingest` call sites keep
# working and can be removed once nothing references it.
from document_pipeline.ingest import *  # noqa: F401,F403
