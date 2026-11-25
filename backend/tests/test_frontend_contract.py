"""The frontend's TypeScript types must match what the backend really returns (guards against invented or missing fields)."""
import re
from pathlib import Path

import pytest

from app.features.google import mapping, service
from test_google_flow import *  # noqa: F401,F403  (fixtures: world, client and helpers)
from test_google_flow import A, inspection, one_target, run_once

TYPES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "google" / "types.ts"


def ts_fields(name: str) -> set[str]:
    src = TYPES.read_text(encoding="utf-8")
    body = re.search(r"export interface " + name + r"\s*\{(.*?)\n\}", src, re.S).group(1)
    return set(re.findall(r"^\s{2}(\w+)\??:", body, re.M))


def test_types_file_is_found():
    assert TYPES.exists(), TYPES


def test_inspection_matches_frontend_type():
    assert set(mapping.map_inspection(inspection()).to_dict()) == ts_fields("Inspection")


async def test_target_history_status_and_properties_match_frontend_types(client, world):
    tid = one_target(client, world)
    await run_once(world)
    target = next(i for i in client.get("/api/v1/google/targets", headers=A).json()["items"] if i["id"] == tid)
    assert set(target) == ts_fields("Target")
    assert set(target["inspection"]) == ts_fields("Inspection")
    entry = client.get(f"/api/v1/google/targets/{tid}/history", headers=A).json()["items"][0]
    assert set(entry) == ts_fields("HistoryEntry")
    status = client.get("/api/v1/google/status", headers=A).json()
    assert set(status) == ts_fields("GoogleStatus") and set(status["quota"]) == ts_fields("GoogleQuota")
    prop = client.get("/api/v1/google/properties", headers=A).json()["properties"][0]
    assert set(prop) == ts_fields("GoogleProperty")
    added = client.post("/api/v1/google/targets", json={"urls": ["https://example.com/new", "https://other.org/x"]}, headers=A).json()
    assert set(added) == ts_fields("AddTargetsResult") and set(added["skipped"][0]) == ts_fields("SkippedUrl")


def test_status_labels_match_the_four_required_names():
    assert mapping.LABELS == {"indexed": "Confirmed Indexed", "not_indexed": "Confirmed Not Indexed",
                              "unknown": "Unknown", "failed": "Inspection Failed"}
    src = (TYPES.parent / "lib" / "labels.ts").read_text(encoding="utf-8")
    for label in mapping.LABELS.values():
        assert label in src, label
