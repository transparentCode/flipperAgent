from __future__ import annotations


def incident_key(incident_id: str) -> str:
    return f"alert:incident:{incident_id}"


def open_incidents_key() -> str:
    return "alert:open_incidents"


def dedupe_key_key(dedupe_key: str) -> str:
    return f"alert:dedupe:{dedupe_key}"


def route_counter_key(route_name: str, window_bucket: int) -> str:
    return f"alert:route_counter:{route_name}:{window_bucket}"


def hot_summary_key() -> str:
    return "alert:summary:hot"

