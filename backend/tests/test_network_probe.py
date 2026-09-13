from unittest.mock import patch

from services import network_probe


def _reset_cache(monkeypatch):
    monkeypatch.setattr(network_probe, "_cached_bandwidth_mbps", None)
    monkeypatch.setattr(network_probe, "_cached_latency_ms", None)
    monkeypatch.setattr(network_probe, "_cached_ok", None)
    monkeypatch.setattr(network_probe, "_cached_at", 0.0)


def test_get_measured_bandwidth_returns_three_values_on_success(monkeypatch):
    _reset_cache(monkeypatch)
    with patch("services.network_probe._measure_real_network", return_value=(42.0, 15.0, True)):
        bandwidth, latency, ok = network_probe.get_measured_bandwidth()
    assert (bandwidth, latency, ok) == (42.0, 15.0, True)


def test_get_measured_bandwidth_reports_not_ok_on_failure(monkeypatch):
    _reset_cache(monkeypatch)
    with patch(
        "services.network_probe._measure_real_network",
        return_value=(network_probe._FALLBACK_BANDWIDTH_MBPS, network_probe._FALLBACK_LATENCY_MS, False),
    ):
        bandwidth, latency, ok = network_probe.get_measured_bandwidth()
    assert ok is False
    assert bandwidth == network_probe._FALLBACK_BANDWIDTH_MBPS
    assert latency == network_probe._FALLBACK_LATENCY_MS


def test_measure_real_network_falls_back_to_not_ok_on_exception():
    with patch("services.network_probe.urllib.request.urlopen", side_effect=OSError("network unreachable")):
        bandwidth, latency, ok = network_probe._measure_real_network()
    assert ok is False
    assert bandwidth == network_probe._FALLBACK_BANDWIDTH_MBPS
    assert latency == network_probe._FALLBACK_LATENCY_MS
