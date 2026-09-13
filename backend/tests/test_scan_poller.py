from unittest.mock import patch

import pytest

import services.scan_poller as scan_poller
from config import Config
from services.state_service import state


@pytest.fixture(autouse=True)
def _reset_started_flag(monkeypatch):
    monkeypatch.setattr(scan_poller, "_started", False)


def test_poll_once_adds_new_connections(client):
    fake = [{"label": "chrome connection to youtube.com on port 443", "hostname": "youtube.com", "port": "443"}]
    with patch("services.scan_poller.network_scan_service.scan_active_connections", return_value=fake):
        added = scan_poller.poll_once()

    assert added == 1
    labels = [t["label"] for t in state.get_traffic_list()]
    assert "chrome connection to youtube.com on port 443" in labels


def test_poll_once_does_not_duplicate_already_tracked_connections(client):
    fake = [{"label": "chrome connection to youtube.com on port 443", "hostname": "youtube.com", "port": "443"}]
    with patch("services.scan_poller.network_scan_service.scan_active_connections", return_value=fake):
        first = scan_poller.poll_once()
        second = scan_poller.poll_once()

    assert first == 1
    assert second == 0
    assert len(state.get_traffic_list()) == 1


def test_poll_once_survives_a_failed_add(client):
    fake = [{"label": "broken connection", "hostname": "x", "port": "1"}]

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated failure")

    with patch("services.scan_poller.network_scan_service.scan_active_connections", return_value=fake), \
         patch("services.scan_poller.state.add_captured_traffic", side_effect=_raise):
        added = scan_poller.poll_once()

    assert added == 0  # failed silently, did not raise out of poll_once


def test_start_only_starts_one_thread(monkeypatch):
    monkeypatch.setattr(Config, "SCAN_POLL_ENABLED", True)
    started = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(scan_poller.threading, "Thread", _FakeThread)
    scan_poller.start()
    scan_poller.start()

    assert len(started) == 1


def test_start_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(Config, "SCAN_POLL_ENABLED", False)
    started = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(scan_poller.threading, "Thread", _FakeThread)
    scan_poller.start()

    assert started == []
