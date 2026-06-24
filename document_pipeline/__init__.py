"""Document normalization / chunking subsystem.

Converts uploaded TXT/PDF/DOCX into canonical Markdown (ingest.py), packs it
into heading-aware chunks (chunker.py), and optionally relabels ambiguous
structure via a local LLM (llm_normalize.py, off by default).
"""
