from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app import database, service
from app.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(service, "now", lambda: datetime(2030, 1, 7, 5, tzinfo=timezone.utc))
    with TestClient(app) as client:
        yield client

def booking(client, slot="2030-01-07T09:00:00+03:00", doctor=1):
    return client.post("/appointments", json={"doctor_id": doctor, "patient_id": 1, "starts_at": slot})

def test_booking_cancel_releases_slot(client):
    result = booking(client)
    assert result.status_code == 201
    assert booking(client).status_code == 409
    url = f"/appointments/{result.json()['id']}/cancel"
    assert client.patch(url, json={"reason": "Change of plans"}).status_code == 200
    assert client.patch(url, json={"reason": "Again"}).status_code == 409
    assert booking(client).status_code == 201

@pytest.mark.parametrize("slot", ["2030-01-07T08:30:00+03:00", "2030-01-07T17:00:00+03:00", "2030-01-07T09:15:00+03:00", "2030-01-12T09:00:00+03:00", "2030-01-07T09:00:00", "2029-01-01T09:00:00+03:00"])
def test_invalid_slots(client, slot):
    assert booking(client, slot).status_code == 422

def test_timezone_equivalence(client):
    assert booking(client).status_code == 201
    assert booking(client, "2030-01-07T06:00:00Z").status_code == 409

def test_reschedule_atomicity(client):
    first = booking(client).json()
    booking(client, "2030-01-07T09:30:00+03:00")
    url = f"/appointments/{first['id']}/reschedule"
    assert client.patch(url, json={"starts_at": "2030-01-07T09:30:00+03:00"}).status_code == 409
    assert booking(client).status_code == 409
    assert client.patch(url, json={"starts_at": "2030-01-07T10:00:00+03:00"}).status_code == 200
    assert booking(client).status_code == 201
    client.patch(f"/appointments/{first['id']}/cancel", json={"reason": "Unavailable"})
    assert client.patch(url, json={"starts_at": "2030-01-07T11:00:00+03:00"}).status_code == 409

def test_availability_and_patient_list(client):
    booking(client, "2030-01-07T10:00:00+03:00")
    booking(client)
    slots = client.get("/doctors/1/availability?date=2030-01-07").json()["slots"]
    assert len(slots) == 14
    assert "2030-01-07T09:00:00+03:00" not in slots
    items = client.get("/patients/1/appointments").json()
    assert [x["starts_at"] for x in items] == sorted(x["starts_at"] for x in items)
    assert client.get("/doctors/1/availability?date=2030-01-12").json()["slots"] == []

def test_missing_records_and_empty_reason(client):
    assert booking(client, doctor=99).status_code == 404
    assert client.get("/doctors/99/availability?date=2030-01-07").status_code == 404
    assert client.patch("/appointments/99/cancel", json={"reason": "Absent"}).status_code == 404
    assert client.patch("/appointments/1/cancel", json={"reason": "  "}).status_code == 422
    assert client.get("/health").status_code == 200
    assert len(client.get("/doctors").json()) == 5

def test_concurrent_booking(client):
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(lambda _: booking(client).status_code, range(6)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 5
