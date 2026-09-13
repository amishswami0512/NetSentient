import pytest

from config import Config
from services.state_service import StateService


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "STATE_DB_PATH", str(tmp_path / "state.db"))
    return tmp_path


def test_state_persists_across_instances(temp_db):
    first = StateService()
    first.add_traffic("emergency", "test alert")
    first.set_congestion(True)
    first.set_semantic_routing(False)

    second = StateService()  # simulates a process restart against the same db file
    traffic = second.get_traffic_list()
    assert len(traffic) == 1
    assert traffic[0]["label"] == "test alert"
    assert traffic[0]["type"] == "emergency"
    assert second.get_congestion() is True
    assert second.get_semantic_routing() is False


def test_reset_clears_traffic_and_flags(temp_db):
    svc = StateService()
    svc.add_traffic("emergency", "test alert")
    svc.set_congestion(True)
    svc.set_semantic_routing(False)

    svc.reset()

    assert svc.get_traffic_list() == []
    assert svc.get_congestion() is False
    assert svc.get_semantic_routing() is True


def test_traffic_ids_increment_and_reset_after_reset(temp_db):
    svc = StateService()
    first = svc.add_traffic("emergency", "a")
    second = svc.add_traffic("video", "b")
    assert first["id"] == "traffic-001"
    assert second["id"] == "traffic-002"

    svc.reset()
    third = svc.add_traffic("file", "c")
    assert third["id"] == "traffic-001"


def test_traffic_list_preserves_insertion_order(temp_db):
    svc = StateService()
    svc.add_traffic("background", "first")
    svc.add_traffic("emergency", "second")
    svc.add_traffic("file", "third")

    labels = [t["label"] for t in svc.get_traffic_list()]
    assert labels == ["first", "second", "third"]


def test_priority_factors_round_trip_as_dict(temp_db):
    svc = StateService()
    entry = svc.add_traffic("emergency", "Ambulance emergency alert dispatched")
    stored = svc.get_traffic_list()[0]
    assert isinstance(stored["priority_factors"], dict)
    for key in ("urgency", "consequence", "latency_sensitivity", "reliability_requirement"):
        assert key in stored["priority_factors"]
    assert stored["priority_factors"] == entry["priority_factors"]


def test_simulation_id_increments(temp_db):
    svc = StateService()
    assert svc.next_simulation_id() == "sim-001"
    assert svc.next_simulation_id() == "sim-002"
    svc.reset()
    assert svc.next_simulation_id() == "sim-001"
