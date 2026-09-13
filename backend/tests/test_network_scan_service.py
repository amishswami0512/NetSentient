import socket
from types import SimpleNamespace
from unittest.mock import patch

import psutil

from services import network_scan_service


def _conn(ip, port, status=psutil.CONN_ESTABLISHED, pid=1234, type=socket.SOCK_STREAM):
    return SimpleNamespace(status=status, raddr=(ip, port), pid=pid, type=type)


def test_scan_active_connections_builds_descriptive_labels():
    conns = [_conn("142.250.1.1", 443)]
    with patch("services.network_scan_service.psutil.net_connections", return_value=conns), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", return_value=("youtube.com", [], [])):
        mock_process.return_value.name.return_value = "chrome"
        results = network_scan_service.scan_active_connections()

    assert len(results) == 1
    assert results[0]["hostname"] == "youtube.com"
    assert results[0]["port"] == "443"
    assert results[0]["label"] == "chrome connection to youtube.com on port 443"
    # Category is deliberately no longer pre-guessed here -- that's now
    # semantic_service's job, same as every other input source.
    assert "type" not in results[0]


def test_scan_active_connections_dedupes_by_ip_and_port():
    conns = [_conn("1.2.3.4", 443), _conn("1.2.3.4", 443)]
    with patch("services.network_scan_service.psutil.net_connections", return_value=conns), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", side_effect=OSError):
        mock_process.return_value.name.return_value = "app"
        results = network_scan_service.scan_active_connections()
    assert len(results) == 1


def test_scan_active_connections_skips_non_established():
    conns = [_conn("1.2.3.4", 443, status=psutil.CONN_CLOSE_WAIT)]
    with patch("services.network_scan_service.psutil.net_connections", return_value=conns):
        assert network_scan_service.scan_active_connections() == []


def test_scan_active_connections_skips_connections_without_remote_address():
    conn = SimpleNamespace(status=psutil.CONN_ESTABLISHED, raddr=None, pid=1)
    with patch("services.network_scan_service.psutil.net_connections", return_value=[conn]):
        assert network_scan_service.scan_active_connections() == []


def test_scan_active_connections_falls_back_to_ip_when_dns_fails():
    conns = [_conn("1.2.3.4", 80)]
    with patch("services.network_scan_service.psutil.net_connections", return_value=conns), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", side_effect=OSError("no dns")):
        mock_process.return_value.name.return_value = "curl"
        results = network_scan_service.scan_active_connections()
    assert results[0]["hostname"] == "1.2.3.4"


def test_scan_active_connections_includes_udp_quic_style_connections():
    # UDP is connectionless -- psutil always reports its status as
    # CONN_NONE, never CONN_ESTABLISHED (confirmed directly against a
    # real UDP socket, not assumed). This is exactly what QUIC/HTTP-3
    # looks like, which is what modern Chrome negotiates by default
    # with most Google properties, YouTube included -- without this,
    # those connections were silently invisible to the scanner.
    conn = _conn("142.250.1.1", 443, status=psutil.CONN_NONE, type=socket.SOCK_DGRAM)
    with patch("services.network_scan_service.psutil.net_connections", return_value=[conn]), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", side_effect=OSError):
        mock_process.return_value.name.return_value = "chrome"
        results = network_scan_service.scan_active_connections()
    assert len(results) == 1


def test_scan_active_connections_skips_udp_without_remote_address():
    conn = _conn("0.0.0.0", 0, status=psutil.CONN_NONE, type=socket.SOCK_DGRAM)
    conn.raddr = None  # a UDP socket that hasn't connect()ed anywhere yet
    with patch("services.network_scan_service.psutil.net_connections", return_value=[conn]):
        assert network_scan_service.scan_active_connections() == []


def test_scan_active_connections_respects_limit():
    conns = [_conn(f"10.0.0.{i}", 443 + i) for i in range(5)]
    with patch("services.network_scan_service.psutil.net_connections", return_value=conns), \
         patch("services.network_scan_service.psutil.Process") as mock_process, \
         patch("services.network_scan_service.socket.gethostbyaddr", side_effect=OSError):
        mock_process.return_value.name.return_value = "app"
        results = network_scan_service.scan_active_connections(limit=2)
    assert len(results) == 2
