from evaluation.qdrant_reconciliation import reconciliation_counts


def test_reconciliation_never_classifies_unknown_by_point_count():
    groups = [
        {"asset_id": "live", "point_count": 448},
        {"asset_id": "retained", "point_count": 550},
        {"asset_id": "temp", "point_count": 9},
        {"asset_id": "orphan", "point_count": 5},
        {"asset_id": "unknown", "point_count": 448},
        {"asset_id": None, "point_count": 3},
    ]
    assert reconciliation_counts(
        groups,
        live_asset_ids={"live"},
        retained_asset_ids={"retained"},
        disposable_asset_ids={"temp"},
        orphan_asset_ids={"orphan"},
    ) == {"A": 448, "B": 550, "C": 9, "D": 5, "E": 451}
