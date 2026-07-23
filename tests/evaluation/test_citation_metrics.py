from evaluation.metrics.citations import evaluate_citations


def test_citation_rates_have_explicit_denominators():
    result = evaluate_citations([
        {
            "citation_required": True,
            "citation_valid": True,
            "citation_document_correct": True,
            "citation_page_correct": False,
            "all_required_claims_cited": False,
            "contains_numeric_claim": True,
            "unsupported_numeric_citation_failure": True,
            "metadata_only_citation_failure": False,
        },
        {
            "citation_required": False,
            "contains_numeric_claim": False,
        },
    ])
    assert result["citation_validity"]["numerator"] == 1
    assert result["citation_validity"]["denominator"] == 1
    assert result["citation_page_accuracy"]["numerator"] == 0
    assert result["unsupported_numeric_citation_failure"]["numerator"] == 1
