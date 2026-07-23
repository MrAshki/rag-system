from __future__ import annotations

from .proportions import proportion_result


def evaluate_citations(records: list[dict]) -> dict:
    def rate(key: str, eligible=lambda row: True) -> dict:
        rows = [row for row in records if eligible(row)]
        return proportion_result(sum(bool(row.get(key)) for row in rows), len(rows))

    required = lambda row: bool(row.get("citation_required", True))
    numeric = lambda row: bool(row.get("contains_numeric_claim"))
    return {
        "citation_validity": rate("citation_valid", required),
        "citation_document_accuracy": rate("citation_document_correct", required),
        "citation_page_accuracy": rate("citation_page_correct", required),
        "citation_recall": rate("all_required_claims_cited", required),
        "unsupported_numeric_citation_failure": rate("unsupported_numeric_citation_failure", numeric),
        "metadata_only_citation_failure": rate("metadata_only_citation_failure", required),
    }
