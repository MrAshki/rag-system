from __future__ import annotations

from .proportions import proportion_result


def _accuracy(records: list[dict], expected_key: str, actual_key: str) -> dict:
    eligible = [row for row in records if row.get(expected_key) is not None]
    return proportion_result(
        sum(row.get(expected_key) == row.get(actual_key) for row in eligible),
        len(eligible),
    )


def evaluate_routing(records: list[dict]) -> dict:
    required = [row for row in records if row.get("retrieval_policy") == "required"]
    forbidden = [row for row in records if row.get("retrieval_policy") == "forbidden"]
    necessity = required + forbidden
    rewrite = [row for row in records if row.get("rewrite_expected") is not None]
    reranker = [row for row in records if row.get("reranker_expected") is not None]
    return {
        "intent_classification_accuracy": _accuracy(records, "expected_intent", "actual_intent"),
        "route_selection_accuracy": _accuracy(records, "expected_route", "actual_route"),
        "retrieval_necessity_accuracy": proportion_result(
            sum(
                bool(row.get("retrieval_called")) == (row["retrieval_policy"] == "required")
                for row in necessity
            ),
            len(necessity),
        ),
        "unnecessary_retrieval_rate": proportion_result(
            sum(bool(row.get("retrieval_called")) for row in forbidden),
            len(forbidden),
        ),
        "missing_retrieval_rate": proportion_result(
            sum(not bool(row.get("retrieval_called")) for row in required),
            len(required),
        ),
        "rewrite_correctness": proportion_result(
            sum(bool(row.get("rewrite_correct")) for row in rewrite),
            len(rewrite),
        ),
        "reranker_call_correctness": proportion_result(
            sum(bool(row.get("reranker_called")) == bool(row.get("reranker_expected")) for row in reranker),
            len(reranker),
        ),
    }
