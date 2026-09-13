import pytest

scapy = pytest.importorskip("scapy.all")

from config import Config  # noqa: E402


@pytest.fixture
def captures_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "CAPTURES_DIR", str(tmp_path))
    return tmp_path


def _write_sample_pcap(path):
    from scapy.all import IP, TCP, wrpcap
    pkt = IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=40000, dport=443)
    wrpcap(str(path), [pkt])


def test_analyze_capture_success(client, captures_dir):
    _write_sample_pcap(captures_dir / "sample.pcap")
    resp = client.post("/api/capture/analyze", json={"pcap_path": "sample.pcap"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["flows_processed"] == 1
    entry = data["traffic"][0]
    for field in ("id", "type", "label", "priority", "priority_factors", "low_confidence", "source"):
        assert field in entry
    assert "flow_metadata" in entry
    assert entry["flow_metadata"]["port"] == 443


def test_analyze_capture_missing_file(client, captures_dir):
    resp = client.post("/api/capture/analyze", json={"pcap_path": "missing.pcap"})
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "NOT_FOUND"


def test_analyze_capture_rejects_path_traversal(client, captures_dir):
    resp = client.post("/api/capture/analyze", json={"pcap_path": "../../../../etc/passwd"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_analyze_capture_rejects_non_pcap_extension(client, captures_dir):
    (captures_dir / "not_a_pcap.txt").write_text("hello")
    resp = client.post("/api/capture/analyze", json={"pcap_path": "not_a_pcap.txt"})
    assert resp.status_code == 400


def test_analyze_capture_missing_pcap_path_field(client):
    resp = client.post("/api/capture/analyze", json={})
    assert resp.status_code == 400
