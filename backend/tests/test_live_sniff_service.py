from unittest.mock import patch

import pytest

scapy = pytest.importorskip("scapy.all")

import services.live_sniff_service as live_sniff_service  # noqa: E402
from config import Config  # noqa: E402
from tests.test_capture_service import _client_hello_with_sni  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache_and_flag(monkeypatch):
    monkeypatch.setattr(live_sniff_service, "_sni_cache", type(live_sniff_service._sni_cache)())
    monkeypatch.setattr(live_sniff_service, "_started", False)
    yield


def _client_hello_packet(dst_ip: str, dst_port: int, hostname: str):
    from scapy.all import IP, TCP, Raw

    payload = _client_hello_with_sni(hostname)
    return IP(dst=dst_ip) / TCP(dport=dst_port) / Raw(load=payload)


def test_get_sni_for_returns_none_when_nothing_recorded():
    assert live_sniff_service.get_sni_for("1.2.3.4", 443) is None


def test_record_sni_populates_cache_from_a_real_packet():
    pkt = _client_hello_packet("142.250.1.1", 443, "youtube.com")
    live_sniff_service._record_sni(pkt)
    assert live_sniff_service.get_sni_for("142.250.1.1", 443) == "youtube.com"


def test_record_sni_ignores_non_443_traffic():
    pkt = _client_hello_packet("10.0.0.1", 8080, "internal.example")
    live_sniff_service._record_sni(pkt)
    assert live_sniff_service.get_sni_for("10.0.0.1", 8080) is None


def test_record_sni_never_raises_on_non_tls_packet():
    from scapy.all import IP, TCP

    plain_packet = IP(dst="1.2.3.4") / TCP(dport=443)  # no Raw/TLS payload at all
    live_sniff_service._record_sni(plain_packet)  # must not raise
    assert live_sniff_service.get_sni_for("1.2.3.4", 443) is None


def test_cache_evicts_oldest_entry_past_max_size(monkeypatch):
    monkeypatch.setattr(live_sniff_service, "_MAX_ENTRIES", 2)
    live_sniff_service._record_sni(_client_hello_packet("1.1.1.1", 443, "a.example"))
    live_sniff_service._record_sni(_client_hello_packet("2.2.2.2", 443, "b.example"))
    live_sniff_service._record_sni(_client_hello_packet("3.3.3.3", 443, "c.example"))

    assert live_sniff_service.get_sni_for("1.1.1.1", 443) is None  # evicted
    assert live_sniff_service.get_sni_for("2.2.2.2", 443) == "b.example"
    assert live_sniff_service.get_sni_for("3.3.3.3", 443) == "c.example"


def test_start_only_starts_one_thread(monkeypatch):
    monkeypatch.setattr(Config, "SNI_SNIFF_ENABLED", True)
    started = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(live_sniff_service.threading, "Thread", _FakeThread)
    live_sniff_service.start()
    live_sniff_service.start()

    assert len(started) == 1


def test_start_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(Config, "SNI_SNIFF_ENABLED", False)
    started = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(live_sniff_service.threading, "Thread", _FakeThread)
    live_sniff_service.start()

    assert started == []


def test_network_scan_prefers_sni_over_reverse_dns():
    from types import SimpleNamespace

    import psutil

    from services import network_scan_service

    live_sniff_service._record_sni(_client_hello_packet("142.250.1.1", 443, "youtube.com"))

    conn = SimpleNamespace(status=psutil.CONN_ESTABLISHED, raddr=("142.250.1.1", 443), pid=123)
    with patch("services.network_scan_service.psutil.net_connections", return_value=[conn]), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", return_value=("ia-in-f91.1e100.net", [], [])):
        mock_process.return_value.name.return_value = "chrome"
        results = network_scan_service.scan_active_connections()

    assert results[0]["hostname"] == "youtube.com"  # SNI wins, not the generic reverse-DNS name
