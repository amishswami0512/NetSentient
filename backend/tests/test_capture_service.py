import pytest

scapy = pytest.importorskip("scapy.all")

from services.capture_service import _extract_sni, extract_flows  # noqa: E402


def _client_hello_with_sni(hostname: str) -> bytes:
    name = hostname.encode("ascii")
    name_entry = b"\x00" + len(name).to_bytes(2, "big") + name
    server_name_list = len(name_entry).to_bytes(2, "big") + name_entry
    extension = b"\x00\x00" + len(server_name_list).to_bytes(2, "big") + server_name_list
    body = (
        b"\x03\x03" + b"\x00" * 32
        + b"\x00"
        + b"\x00\x00"
        + b"\x00"
        + len(extension).to_bytes(2, "big") + extension
    )
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake


def test_extract_sni_parses_client_hello():
    assert _extract_sni(_client_hello_with_sni("example.com")) == "example.com"


@pytest.mark.parametrize("garbage", [b"", b"\x00" * 5, b"\x16\x03\x01\x00\x04junk", b"\x17not tls at all"])
def test_extract_sni_never_raises_on_garbage(garbage):
    assert _extract_sni(garbage) is None


def test_extract_flows_from_synthetic_pcap(tmp_path):
    from scapy.all import DNS, DNSQR, IP, TCP, UDP, wrpcap

    dns_pkt = IP(src="10.0.0.1", dst="8.8.8.8") / UDP(sport=51000, dport=53) / DNS(rd=1, qd=DNSQR(qname="example.org"))
    http_packets = [
        IP(src="10.0.0.2", dst="93.184.216.34") / TCP(sport=52000, dport=80, flags="S")
        for _ in range(3)
    ]

    pcap_path = tmp_path / "sample.pcap"
    wrpcap(str(pcap_path), [dns_pkt, *http_packets])

    flows = extract_flows(str(pcap_path))
    descriptions = [f["description"] for f in flows]

    assert any("DNS lookup for 'example.org'" in d for d in descriptions)
    assert any("port 80" in d and "HTTP" in d for d in descriptions)

    http_flow = next(f for f in flows if f["port"] == 80)
    assert http_flow["packet_count"] == 3
    assert http_flow["protocol"] == "tcp"
    assert http_flow["sni"] is None
    assert http_flow["dns_name"] is None


def test_extract_flows_caps_at_max_flows(tmp_path):
    from scapy.all import IP, TCP, wrpcap

    packets = [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=40000 + i, dport=8000 + i) for i in range(5)]
    pcap_path = tmp_path / "many_flows.pcap"
    wrpcap(str(pcap_path), packets)

    assert len(extract_flows(str(pcap_path), max_flows=2)) == 2


def test_extract_flows_skips_non_ip_packets_without_crashing(tmp_path):
    from scapy.all import ARP, Ether, IP, TCP, wrpcap

    arp_pkt = Ether() / ARP()
    tcp_pkt = Ether() / IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1234, dport=443)
    pcap_path = tmp_path / "mixed.pcap"
    wrpcap(str(pcap_path), [arp_pkt, tcp_pkt])

    flows = extract_flows(str(pcap_path))
    assert len(flows) == 1
    assert flows[0]["port"] == 443
