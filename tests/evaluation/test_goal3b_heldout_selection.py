from __future__ import annotations

from evaluation.runners.select_goal3b_heldout import (
    CORE_CONVERSATION_IDS,
    CORE_SINGLE_IDS,
    DEFAULT_SEED,
    EXCLUDED_FILENAMES,
    build_selection,
)


def test_goal3b_heldout_selection_is_reproducible_and_preregistered():
    first = build_selection(DEFAULT_SEED)
    second = build_selection(DEFAULT_SEED)
    assert first == second
    assert first["provider_execution_count"] == 0
    assert len(first["selected_ids"]) == 12


def test_goal3b_heldout_selection_has_required_diversity_and_no_leakage():
    selection = build_selection(DEFAULT_SEED)
    rows = selection["selected"]
    ids = set(selection["selected_ids"])
    types = selection["task_type_distribution"]

    assert not ids.intersection(CORE_SINGLE_IDS | CORE_CONVERSATION_IDS)
    assert all(row["filename"] not in EXCLUDED_FILENAMES for row in rows)
    assert selection["distinct_documents"] >= 8
    assert selection["fixture_task_count"] <= 2
    assert types["local_factual"] >= 3
    assert types["table_or_numerical"] >= 2
    assert types["cross_language"] >= 1
    assert types["no_answer_or_conflict"] >= 1
    assert types["quoted_document_explanation"] >= 1
    assert types["conversation_turn"] >= 1
    assert types["comprehensive_summary"] + types["analytical"] >= 2
