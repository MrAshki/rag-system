"""Pure ownership classification used by Qdrant/PostgreSQL audits."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping


def classify_group(
    group: Mapping[str, object],
    *,
    live_asset_ids: set[str],
    retained_asset_ids: set[str],
    disposable_asset_ids: set[str],
    orphan_asset_ids: set[str],
) -> str:
    """Classify a point group without inferring safety from point counts."""
    asset_id = str(group.get("asset_id") or "")
    if asset_id and asset_id in live_asset_ids:
        return "A"
    if asset_id and asset_id in retained_asset_ids:
        return "B"
    if asset_id and asset_id in disposable_asset_ids:
        return "C"
    if asset_id and asset_id in orphan_asset_ids:
        return "D"
    return "E"


def reconciliation_counts(
    groups: Iterable[Mapping[str, object]],
    **ownership_sets: set[str],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for group in groups:
        category = classify_group(group, **ownership_sets)
        counts[category] += int(group.get("point_count") or 0)
    return {category: counts[category] for category in "ABCDE"}
