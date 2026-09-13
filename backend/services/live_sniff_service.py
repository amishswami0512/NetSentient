"""Live TLS/QUIC SNI sniffing: watches real outbound HTTPS and HTTP-3
handshakes on a network interface and remembers which hostname each
(ip, port) pair was actually talking to -- the same unencrypted
ClientHello field capture_service.py already reads from recorded
pcaps, just read live instead of from a file.

This exists because reverse DNS (network_scan_service.py's original
approach) is unreliable for exactly the sites you'd most want
classified correctly: YouTube, Gmail, and most Google-hosted services
all reverse-resolve to generic infrastructure hostnames like
"ia-in-f91.1e100.net", not "youtube.com" -- confirmed by testing
against Google's own real IPs, not assumed.

Two transports carry that handshake, and both are handled:
- Plain TLS-over-TCP: the ClientHello is sent unencrypted; just read it.
- QUIC (HTTP/3, UDP): confirmed separately that psutil reports UDP
  connections as CONN_NONE, never ESTABLISHED, so network_scan_service.py
  had to be fixed first just to *see* these connections at all (they're
  what modern Chrome negotiates by default with most Google properties,
  YouTube included). QUIC's Initial packets -- the only ones carrying
  the ClientHello -- are encrypted, but with keys derived entirely from
  public values (a fixed salt + the packet's own visible connection ID,
  per RFC 9001 section 5.2), not a real secret. Decryption here uses
  `aioquic`, a well-tested, RFC 9001-compliant implementation, rather
  than hand-rolled crypto -- validated directly against the RFC's own
  official test vector before trusting it on live traffic (bit-exact
  match, not just "it ran without an error").

Needs to actually see raw packets on a real interface, which needs
root/CAP_NET_RAW (same requirement as `tcpdump`) -- off by default
(Config.SNI_SNIFF_ENABLED). Missing scapy/aioquic, missing privilege,
a non-QUIC/non-v1 packet, or any parse/decrypt failure all degrade
silently to "no SNI for this one" -- network_scan_service.py falls
back to reverse DNS exactly as before this existed, never a crash.
"""
import logging
import threading
from collections import OrderedDict
from typing import Any

from config import Config

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 500
_sni_cache: "OrderedDict[tuple[str, int], str]" = OrderedDict()
_cache_lock = threading.Lock()

# QUIC ClientHellos are often split across more than one Initial
# packet's CRYPTO frame (real browser ClientHellos, with a full
# extension set, routinely exceed what fits in one). Fragments are
# kept per (ip, port) until they assemble into a complete handshake
# message or this bound evicts the oldest entry -- best-effort, not a
# full QUIC connection state machine.
_MAX_FRAGMENT_FLOWS = 200
_crypto_fragments: "OrderedDict[tuple[str, int], dict[int, bytes]]" = OrderedDict()

_started = False
_start_lock = threading.Lock()


def get_sni_for(ip: str, port: int) -> str | None:
    """Never raises, never blocks -- a plain dict read. Safe to call
    regardless of whether sniffing is enabled, running, or supported
    on this platform at all.
    """
    with _cache_lock:
        return _sni_cache.get((ip, port))


def _store_sni(key: tuple[str, int], sni: str) -> None:
    with _cache_lock:
        _sni_cache[key] = sni
        _sni_cache.move_to_end(key)
        while len(_sni_cache) > _MAX_ENTRIES:
            _sni_cache.popitem(last=False)


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """QUIC's variable-length integer encoding (RFC 9000 section 16):
    the top 2 bits of the first byte pick the encoded length (1/2/4/8
    bytes), the rest is the value.
    """
    first = data[pos]
    length = 1 << (first >> 6)
    value = first & 0x3F
    for i in range(1, length):
        value = (value << 8) | data[pos + i]
    return value, pos + length


def _collect_crypto_frames(payload: bytes) -> list[tuple[int, bytes]]:
    """Walks a decrypted QUIC Initial packet's frames, collecting any
    CRYPTO frames (type 0x06) as (offset, data) pairs. Stops at the
    first frame type it doesn't need to understand (anything but
    PADDING/PING/CRYPTO) rather than guessing how to skip it --
    whatever CRYPTO data was already found is still used.
    """
    frames: list[tuple[int, bytes]] = []
    pos = 0
    n = len(payload)
    while pos < n:
        frame_type = payload[pos]
        pos += 1
        if frame_type == 0x00 or frame_type == 0x01:  # PADDING / PING: no body
            continue
        if frame_type == 0x06:  # CRYPTO
            offset, pos = _read_varint(payload, pos)
            length, pos = _read_varint(payload, pos)
            frames.append((offset, payload[pos:pos + length]))
            pos += length
            continue
        break  # ACK or anything else: not worth hand-parsing just to skip
    return frames


def _assemble_handshake(key: tuple[str, int]) -> bytes | None:
    """Merges whatever contiguous fragment we have starting at offset
    0. Returns None if we don't have enough yet to even read the TLS
    Handshake header's declared length, or enough bytes to cover it.
    """
    fragments = _crypto_fragments.get(key)
    if not fragments or 0 not in fragments:
        return None

    assembled = bytearray()
    next_offset = 0
    for offset in sorted(fragments):
        if offset != next_offset:
            break  # gap -- stop at the last contiguous byte we have
        assembled.extend(fragments[offset])
        next_offset = offset + len(fragments[offset])

    if len(assembled) < 4:
        return None
    declared_length = int.from_bytes(bytes(assembled[1:4]), "big")
    if len(assembled) < 4 + declared_length:
        return None
    return bytes(assembled[:4 + declared_length])


def _extract_sni_quic(dst_ip: str, dst_port: int, udp_payload: bytes) -> None:
    """Decrypts a QUIC Initial packet (if that's what this is) and
    feeds any CRYPTO frame data toward assembling a full ClientHello.
    Only Initial packets are handled -- they're the only QUIC packet
    type whose keys are derivable from public information alone; every
    later packet type uses real negotiated session keys this process
    has no way to obtain, by design.
    """
    try:
        from aioquic.buffer import Buffer
        from aioquic.quic.crypto import CryptoPair
        from aioquic.quic.packet import QuicPacketType, QuicProtocolVersion, is_long_header, pull_quic_header
    except ImportError:
        return

    try:
        if not udp_payload or not is_long_header(udp_payload[0]):
            return  # short-header (1-RTT) packets use real session keys -- never readable here

        buf = Buffer(data=udp_payload)
        header = pull_quic_header(buf, host_cid_length=8)
        if header.packet_type != QuicPacketType.INITIAL:
            return
        if header.version != QuicProtocolVersion.VERSION_1:
            return  # only QUIC v1's key derivation is implemented here

        encrypted_offset = buf.tell()
        pair = CryptoPair()
        # is_client=False: we're decrypting a packet the *client* sent
        # (the browser's own ClientHello), which needs the "client in"
        # secret -- that's the role CryptoPair derives for recv when
        # set up as the server side, regardless of what this process
        # actually is.
        pair.setup_initial(cid=header.destination_cid, is_client=False, version=header.version)
        _plain_header, payload, _packet_number = pair.decrypt_packet(udp_payload, encrypted_offset, 0)
    except Exception:
        return  # not every UDP:443 packet is QUIC, and not every QUIC packet is decryptable here

    key = (dst_ip, dst_port)
    for offset, data in _collect_crypto_frames(payload):
        fragments = _crypto_fragments.setdefault(key, {})
        fragments[offset] = data
        _crypto_fragments.move_to_end(key)
    while len(_crypto_fragments) > _MAX_FRAGMENT_FLOWS:
        _crypto_fragments.popitem(last=False)

    handshake = _assemble_handshake(key)
    if handshake is None:
        return

    from services.capture_service import extract_sni_from_handshake

    sni = extract_sni_from_handshake(handshake)
    _crypto_fragments.pop(key, None)  # done with this flow's fragments either way
    if sni:
        _store_sni(key, sni)


def _record_sni(pkt: Any) -> None:
    from services.capture_service import _extract_sni  # reuse, don't duplicate

    try:
        from scapy.all import IP, TCP, UDP, Raw
    except ImportError:
        return

    try:
        if IP not in pkt or Raw not in pkt:
            return

        if TCP in pkt:
            if int(pkt[TCP].dport) != 443:
                return  # only ClientHellos (client -> server) carry the SNI we want
            sni = _extract_sni(bytes(pkt[Raw].load))
            if sni:
                _store_sni((pkt[IP].dst, int(pkt[TCP].dport)), sni)
            return

        if UDP in pkt:
            if int(pkt[UDP].dport) != 443:
                return
            _extract_sni_quic(pkt[IP].dst, int(pkt[UDP].dport), bytes(pkt[Raw].load))
    except Exception:
        logger.exception("Failed to process a sniffed packet")


def _resolve_interface(explicit: str | None):
    if explicit:
        return explicit
    from scapy.all import conf

    return conf.iface


def _run_forever() -> None:
    try:
        from scapy.all import sniff
    except ImportError:
        logger.warning("Live SNI sniffing disabled: scapy is not installed.")
        return

    interface = _resolve_interface(Config.SNI_SNIFF_INTERFACE)
    try:
        logger.info("Live SNI sniffing started on interface %s", interface)
        sniff(iface=interface, filter="tcp port 443 or udp port 443", prn=_record_sni, store=False)
    except PermissionError:
        logger.warning(
            "Live SNI sniffing needs elevated privileges (like tcpdump does) -- "
            "run the server with sudo/administrator rights to enable it. "
            "Falling back to reverse-DNS hostname resolution."
        )
    except Exception:
        logger.exception("Live SNI sniffing stopped unexpectedly on interface %s", interface)


def start() -> None:
    """Idempotent -- safe to call from every worker/reloader process
    that imports this module.
    """
    global _started
    with _start_lock:
        if _started or not Config.SNI_SNIFF_ENABLED:
            return
        _started = True
    thread = threading.Thread(target=_run_forever, name="sni-sniffer", daemon=True)
    thread.start()
