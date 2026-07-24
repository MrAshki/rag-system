from __future__ import annotations

from .proportions import proportion_result


def evaluate_conversations(records: list[dict]) -> dict:
    count = len(records)
    forbidden = [row for row in records if row.get("retrieval_policy") == "forbidden"]
    return {
        "followup_resolution_accuracy": proportion_result(sum(bool(row.get("followup_resolved")) for row in records), count),
        "history_use_accuracy": proportion_result(sum(bool(row.get("history_used_correctly")) for row in records), count),
        "unnecessary_retrieval_rate": proportion_result(sum(bool(row.get("retrieval_called")) for row in forbidden), len(forbidden)),
        "selected_asset_persistence": proportion_result(sum(bool(row.get("selected_asset_persisted")) for row in records), count),
        "conversation_id_persistence": proportion_result(sum(bool(row.get("conversation_id_persisted")) for row in records), count),
    }
