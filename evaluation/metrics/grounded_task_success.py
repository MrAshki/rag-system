from __future__ import annotations

from .proportions import proportion_result


REQUIRED_GTS_CONDITIONS = (
    "route_correct",
    "evidence_available",
    "answer_correct",
    "required_concepts_covered",
    "grounded",
    "citations_correct",
    "output_complete",
    "no_internal_message_exposed",
)


def grounded_task_success(record: dict) -> int:
    """Strict binary conjunction; missing conditions fail."""
    return int(all(record.get(name) is True for name in REQUIRED_GTS_CONDITIONS))


def aggregate_grounded_task_success(records: list[dict], route_key: str = "expected_route") -> dict:
    overall = proportion_result(sum(grounded_task_success(row) for row in records), len(records))
    routes = {}
    for route in sorted({str(row.get(route_key)) for row in records}):
        subset = [row for row in records if str(row.get(route_key)) == route]
        routes[route] = proportion_result(sum(grounded_task_success(row) for row in subset), len(subset))
    return {"overall": overall, "per_route": routes}
