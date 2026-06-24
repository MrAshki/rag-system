# Temporary backward-compatible shim. The real implementation moved to
# document_pipeline/chunker.py. New code should import from document_pipeline
# directly; this file exists only so old `import chunker` call sites keep
# working and can be removed once nothing references it.
from document_pipeline.chunker import *  # noqa: F401,F403
from document_pipeline.chunker import _pack_section_group  # noqa: F401
