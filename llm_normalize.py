# Temporary backward-compatible shim. The real implementation moved to
# document_pipeline/llm_normalize.py. New code should import from
# document_pipeline directly; this file exists only so old
# `import llm_normalize` call sites keep working and can be removed once
# nothing references it.
from document_pipeline.llm_normalize import *  # noqa: F401,F403
