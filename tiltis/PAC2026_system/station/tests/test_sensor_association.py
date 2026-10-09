import json
import sqlite3

import httpx
import pytest

from sensor_client import SensorClient
from store import Store


def client_with_handler(mutate=None):
    client = SensorClient("http://synthetic")
    client._http.close()
    def handler(request):
        body = json.loads(request.content)
        base = {k: body[k] for k in ("session", "specimen_id", "face", "attempt", "trigger_id")}
        result = {**base, "capture_id": "synthetic-capture", "status": "ok", "error": None,
            "verdict": "review", "reasons": ["defect_rules_unavailable"], "features": {}, "images": {},
            "sensor_data": {"schema_version": "pac-sensors-1", "association": {
                **base, "capture_id": "synthetic-capture", "status": "linked_by_request_only"}}, "artifacts": {}}
        if mutate: mutate(result)
        return httpx.Response(200, json=result)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize("key, value", [("session", "OTHER"), ("trigger_id", "OLD"),
    ("specimen_id", "OTHER"), ("face", "B"), ("attempt", 1), ("capture_id", "OTHER")])
def test_nested_other_object_or_trigger_is_rejected(key, value):
    client = client_with_handler(lambda result: result["sensor_data"]["association"].update({key: value}))
    try:
        assert client.inspect("t", "S01", "A", 0)["status"] == "error"
    finally: client.close()


def test_same_specimen_repeats_and_retakes_have_unique_triggers():
    client = client_with_handler()
    try:
        responses = [client.inspect("t", "S01", "A", attempt) for attempt in (0, 1, 0)]
        assert all(r["status"] == "ok" for r in responses)
        assert len({r["trigger_id"] for r in responses}) == 3
        assert all(r["sensor_data"]["association"]["trigger_id"] == r["trigger_id"] for r in responses)
    finally: client.close()


@pytest.mark.parametrize("key", ["sensor_data", "artifacts"])
def test_malformed_extended_sensor_payload_is_rejected(key):
    client = client_with_handler(lambda result: result.update({key: []}))
    try: assert client.inspect("t", "S01", "A", 0)["status"] == "error"
    finally: client.close()


def test_old_record_database_migration_preserves_existing_inspections(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE inspections (run_id INTEGER, face TEXT, attempt INTEGER, status TEXT,"
            "verdict TEXT, reasons TEXT, features TEXT, capture_id TEXT, images TEXT, elapsed_ms INTEGER)")
        connection.execute("INSERT INTO inspections VALUES (1,'A',0,'ok','review','[]','{\"old\":1}','old','{}',1)")
    store = Store(path)
    saved = store.get_inspections(1)[0]
    assert saved["capture_id"] == "old" and saved["features"] == {"old": 1}
    assert saved["sensor_data"] is None and saved["trigger_id"] is None
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(inspections)")}
    assert {"advisor", "sensor_data", "artifacts", "trigger_id"} <= columns
