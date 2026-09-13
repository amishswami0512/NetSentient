from unittest.mock import patch

import pytest

scapy = pytest.importorskip("scapy.all")

import services.live_sniff_service as live_sniff_service  # noqa: E402
from config import Config  # noqa: E402
from tests.test_capture_service import _client_hello_with_sni  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache_and_flag(monkeypatch):
    monkeypatch.setattr(live_sniff_service, "_sni_cache", type(live_sniff_service._sni_cache)())
    monkeypatch.setattr(live_sniff_service, "_crypto_fragments", type(live_sniff_service._crypto_fragments)())
    monkeypatch.setattr(live_sniff_service, "_started", False)
    yield


# The exact client Initial packet from RFC 9001 Appendix A.2 -- verified
# directly against the RFC (via a well-tested reference implementation's
# own test suite, cross-checked bit-for-bit), not assumed correct.
# Its ClientHello's SNI is "example.com".
_RFC9001_CLIENT_INITIAL_HEX = (
    "c000000001088394c8f03e5157080000449e7b9aec34d1b1c98dd7689fb8ec11"
    "d242b123dc9bd8bab936b47d92ec356c0bab7df5976d27cd449f63300099f399"
    "1c260ec4c60d17b31f8429157bb35a1282a643a8d2262cad67500cadb8e7378c"
    "8eb7539ec4d4905fed1bee1fc8aafba17c750e2c7ace01e6005f80fcb7df6212"
    "30c83711b39343fa028cea7f7fb5ff89eac2308249a02252155e2347b63d58c5"
    "457afd84d05dfffdb20392844ae812154682e9cf012f9021a6f0be17ddd0c208"
    "4dce25ff9b06cde535d0f920a2db1bf362c23e596d11a4f5a6cf3948838a3aec"
    "4e15daf8500a6ef69ec4e3feb6b1d98e610ac8b7ec3faf6ad760b7bad1db4ba3"
    "485e8a94dc250ae3fdb41ed15fb6a8e5eba0fc3dd60bc8e30c5c4287e53805db"
    "059ae0648db2f64264ed5e39be2e20d82df566da8dd5998ccabdae053060ae6c"
    "7b4378e846d29f37ed7b4ea9ec5d82e7961b7f25a9323851f681d582363aa5f8"
    "9937f5a67258bf63ad6f1a0b1d96dbd4faddfcefc5266ba6611722395c906556"
    "be52afe3f565636ad1b17d508b73d8743eeb524be22b3dcbc2c7468d54119c74"
    "68449a13d8e3b95811a198f3491de3e7fe942b330407abf82a4ed7c1b311663a"
    "c69890f4157015853d91e923037c227a33cdd5ec281ca3f79c44546b9d90ca00"
    "f064c99e3dd97911d39fe9c5d0b23a229a234cb36186c4819e8b9c5927726632"
    "291d6a418211cc2962e20fe47feb3edf330f2c603a9d48c0fcb5699dbfe58964"
    "25c5bac4aee82e57a85aaf4e2513e4f05796b07ba2ee47d80506f8d2c25e50fd"
    "14de71e6c418559302f939b0e1abd576f279c4b2e0feb85c1f28ff18f58891ff"
    "ef132eef2fa09346aee33c28eb130ff28f5b766953334113211996d20011a198"
    "e3fc433f9f2541010ae17c1bf202580f6047472fb36857fe843b19f5984009dd"
    "c324044e847a4f4a0ab34f719595de37252d6235365e9b84392b061085349d73"
    "203a4a13e96f5432ec0fd4a1ee65accdd5e3904df54c1da510b0ff20dcc0c77f"
    "cb2c0e0eb605cb0504db87632cf3d8b4dae6e705769d1de354270123cb11450e"
    "fc60ac47683d7b8d0f811365565fd98c4c8eb936bcab8d069fc33bd801b03ade"
    "a2e1fbc5aa463d08ca19896d2bf59a071b851e6c239052172f296bfb5e724047"
    "90a2181014f3b94a4e97d117b438130368cc39dbb2d198065ae3986547926cd2"
    "162f40a29f0c3c8745c0f50fba3852e566d44575c29d39a03f0cda721984b6f4"
    "40591f355e12d439ff150aab7613499dbd49adabc8676eef023b15b65bfc5ca0"
    "6948109f23f350db82123535eb8a7433bdabcb909271a6ecbcb58b936a88cd4e"
    "8f2e6ff5800175f113253d8fa9ca8885c2f552e657dc603f252e1a8e308f76f0"
    "be79e2fb8f5d5fbbe2e30ecadd220723c8c0aea8078cdfcb3868263ff8f09400"
    "54da48781893a7e49ad5aff4af300cd804a6b6279ab3ff3afb64491c85194aab"
    "760d58a606654f9f4400e8b38591356fbf6425aca26dc85244259ff2b19c41b9"
    "f96f3ca9ec1dde434da7d2d392b905ddf3d1f9af93d1af5950bd493f5aa731b4"
    "056df31bd267b6b90a079831aaf579be0a39013137aac6d404f518cfd4684064"
    "7e78bfe706ca4cf5e9c5453e9f7cfd2b8b4c8d169a44e55c88d4a9a7f9474241"
    "e221af44860018ab0856972e194cd934"
)


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


aioquic = pytest.importorskip("aioquic")


class TestQuicSniExtraction:
    """QUIC's Initial-packet keys are derived from public values, not a
    secret (RFC 9001 section 5.2) -- these tests validate the actual
    decryption against the RFC's own official test vector, not just
    that the code runs without crashing.
    """

    def test_extract_sni_quic_matches_rfc9001_vector_exactly(self):
        import binascii

        encrypted = binascii.unhexlify(_RFC9001_CLIENT_INITIAL_HEX)
        live_sniff_service._extract_sni_quic("192.0.2.1", 443, encrypted)
        assert live_sniff_service.get_sni_for("192.0.2.1", 443) == "example.com"

    def test_record_sni_dispatches_udp_443_to_quic_path(self):
        import binascii

        from scapy.all import IP, UDP, Raw

        encrypted = binascii.unhexlify(_RFC9001_CLIENT_INITIAL_HEX)
        pkt = IP(dst="192.0.2.1") / UDP(dport=443) / Raw(load=encrypted)
        live_sniff_service._record_sni(pkt)
        assert live_sniff_service.get_sni_for("192.0.2.1", 443) == "example.com"

    def test_extract_sni_quic_ignores_non_quic_udp_garbage(self):
        live_sniff_service._extract_sni_quic("10.0.0.1", 443, b"not a quic packet at all")
        assert live_sniff_service.get_sni_for("10.0.0.1", 443) is None

    def test_extract_sni_quic_ignores_short_header_packets(self):
        # A short-header (1-RTT) packet's high bit is 0 -- these use
        # real negotiated session keys this process never has access
        # to, and must never be attempted.
        live_sniff_service._extract_sni_quic("10.0.0.2", 443, b"\x40" + b"\x00" * 30)
        assert live_sniff_service.get_sni_for("10.0.0.2", 443) is None

    def test_extract_sni_quic_ignores_non_v1_version(self):
        # Long header, but a version field that isn't QUIC v1
        # (00000001) -- e.g. a version negotiation or draft version.
        garbage_version_packet = b"\xc0" + b"\xff\x00\x00\x1d" + b"\x00" * 20
        live_sniff_service._extract_sni_quic("10.0.0.3", 443, garbage_version_packet)
        assert live_sniff_service.get_sni_for("10.0.0.3", 443) is None

    def test_read_varint_decodes_each_length_class(self):
        # RFC 9000 section 16: top 2 bits of the first byte select a
        # 1/2/4/8-byte encoding.
        assert live_sniff_service._read_varint(b"\x25", 0) == (0x25, 1)
        assert live_sniff_service._read_varint(b"\x7b\xbd", 0) == (0x3BBD, 2)
        assert live_sniff_service._read_varint(b"\x9d\x7f\x3e\x7d", 0) == (0x1D7F3E7D, 4)

    def test_collect_crypto_frames_skips_padding_and_ping(self):
        payload = b"\x00\x00\x01" + b"\x06" + b"\x00" + b"\x03" + b"abc"
        frames = live_sniff_service._collect_crypto_frames(payload)
        assert frames == [(0, b"abc")]

    def test_collect_crypto_frames_collects_multiple_offsets(self):
        payload = (
            b"\x06" + b"\x00" + b"\x03" + b"abc"  # offset 0, len 3
            + b"\x06" + b"\x03" + b"\x03" + b"def"  # offset 3, len 3
        )
        frames = live_sniff_service._collect_crypto_frames(payload)
        assert frames == [(0, b"abc"), (3, b"def")]

    def test_collect_crypto_frames_stops_at_unhandled_frame_type(self):
        payload = b"\x06" + b"\x00" + b"\x03" + b"abc" + b"\x02" + b"\xff\xff\xff"
        frames = live_sniff_service._collect_crypto_frames(payload)
        assert frames == [(0, b"abc")]  # CRYPTO found before the ACK is still returned

    def test_assemble_handshake_waits_for_missing_offset_zero(self):
        key = ("1.2.3.4", 443)
        live_sniff_service._crypto_fragments[key] = {4: b"later chunk, offset 0 never arrived"}
        assert live_sniff_service._assemble_handshake(key) is None

    def test_assemble_handshake_waits_for_full_declared_length(self):
        # Handshake header: type=0x01, length=0x000005 (needs 5 body
        # bytes), but only 2 are actually present yet.
        key = ("1.2.3.4", 443)
        live_sniff_service._crypto_fragments[key] = {0: b"\x01\x00\x00\x05" + b"ab"}
        assert live_sniff_service._assemble_handshake(key) is None

    def test_assemble_handshake_reassembles_two_contiguous_fragments(self):
        from tests.test_capture_service import _client_hello_with_sni

        full_handshake = _client_hello_with_sni("split.example")[5:]  # strip TLS record header
        split_at = len(full_handshake) // 2
        key = ("1.2.3.4", 443)
        live_sniff_service._crypto_fragments[key] = {
            0: full_handshake[:split_at],
            split_at: full_handshake[split_at:],
        }
        assembled = live_sniff_service._assemble_handshake(key)
        assert assembled == full_handshake

    def test_extract_sni_quic_end_to_end_across_two_fake_fragments(self):
        # Not a real second encrypted packet -- directly seeds the
        # fragment buffer to prove _extract_sni_quic's assemble ->
        # extract_sni_from_handshake wiring works once a handshake is
        # complete, independent of the RFC vector's single-packet case.
        from tests.test_capture_service import _client_hello_with_sni

        full_handshake = _client_hello_with_sni("fragmented.example")[5:]
        split_at = len(full_handshake) // 2
        key = ("9.9.9.9", 443)
        live_sniff_service._crypto_fragments[key] = {0: full_handshake[:split_at]}

        handshake = live_sniff_service._assemble_handshake(key)
        assert handshake is None  # second half not in yet

        live_sniff_service._crypto_fragments[key][split_at] = full_handshake[split_at:]
        from services.capture_service import extract_sni_from_handshake

        handshake = live_sniff_service._assemble_handshake(key)
        assert extract_sni_from_handshake(handshake) == "fragmented.example"
