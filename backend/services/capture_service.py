"""Turns real captured network traffic into semantic descriptions.

This is the only module that touches packet bytes. Its job ends at
producing a factual, honest description per flow ("Encrypted TLS
session to 'zoom.us' on port 443, ...") -- it never guesses a category
or a priority itself. Those descriptions feed into the exact same
semantic_service.analyze() / priority_service.score() pipeline that
POST /api/classify already uses, so real captured traffic is judged by
the same rules as a hand-typed description.

Each flow also gets a `signature` -- a stable identity for the flow
*pattern* (e.g. "tls:zoom.us:443"), separate from its `description`
(which bakes in this observation's packet/byte counts and so is
different every time, even for the same underlying pattern). Callers
should pass `signature` as semantic_service.analyze()'s `cache_key` so
repeat traffic to the same host is classified by Gemini once, not once
per capture.

scapy is an optional dependency (like google-genai): importing it
happens lazily, inside extract_flows(), so the rest of the app runs
fine without it installed -- only POST /api/capture/analyze needs it.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_WELL_KNOWN_PORTS = {
    20: "FTP data", 21: "FTP control", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 80: "HTTP", 110: "POP3", 123: "NTP", 143: "IMAP",
    443: "HTTPS/TLS", 445: "SMB", 587: "SMTP submission", 993: "IMAPS",
    995: "POP3S", 3389: "RDP", 5060: "SIP", 5222: "XMPP",
}


class CaptureUnavailable(Exception):
    """Raised when scapy isn't installed. Distinct from a bad pcap file
    (which is handled per-packet, never raises) -- this means the
    feature itself can't run at all.
    """


def _extract_sni(payload: bytes) -> str | None:
    """Best-effort manual parse of a TLS-over-TCP record's ClientHello
    SNI extension (payload includes the 5-byte TLS record header).

    Deliberately hand-rolled instead of pulling in scapy's TLS layer
    (which needs the `cryptography` package) or a full TLS library --
    we only ever need to read one plaintext field out of the
    unencrypted handshake, never anything past it. Any malformed,
    truncated, or non-ClientHello payload returns None rather than
    raising -- pcap contents are untrusted external data.
    """
    try:
        if len(payload) < 5 or payload[0] != 0x16:
            return None
        return extract_sni_from_handshake(payload[5:])
    except (IndexError, ValueError):
        return None


def extract_sni_from_handshake(handshake: bytes) -> str | None:
    """Same parse as _extract_sni, but starting directly at the TLS
    Handshake message (type + 3-byte length + body) with no record
    header in front of it -- this is what QUIC carries in its CRYPTO
    frames (services/live_sniff_service.py's QUIC path), unlike
    TLS-over-TCP which wraps it in a record header first. Shared here
    so both paths parse the ClientHello body identically.
    """
    try:
        if len(handshake) < 4 or handshake[0] != 0x01:
            return None
        body = handshake[4:]

        pos = 2 + 32  # client_version, random
        session_id_len = body[pos]
        pos += 1 + session_id_len
        cipher_suites_len = int.from_bytes(body[pos:pos + 2], "big")
        pos += 2 + cipher_suites_len
        compression_len = body[pos]
        pos += 1 + compression_len

        extensions_len = int.from_bytes(body[pos:pos + 2], "big")
        pos += 2
        end = pos + extensions_len

        while pos < end:
            ext_type = int.from_bytes(body[pos:pos + 2], "big")
            pos += 2
            ext_len = int.from_bytes(body[pos:pos + 2], "big")
            pos += 2
            if ext_type == 0:  # server_name
                sni_pos = pos + 2  # skip server_name_list length
                sni_pos += 1  # skip name_type
                name_len = int.from_bytes(body[sni_pos:sni_pos + 2], "big")
                sni_pos += 2
                return body[sni_pos:sni_pos + name_len].decode("ascii", errors="ignore") or None
            pos += ext_len
        return None
    except (IndexError, ValueError):
        return None


def _describe_flow(
    proto: str, dport: int, sni: str | None, dns_name: str | None,
    packet_count: int, total_bytes: int, duration: float,
) -> str:
    if sni:
        return (
            f"Encrypted TLS session to '{sni}' on port {dport}, "
            f"{packet_count} packets / {total_bytes} bytes over {duration:.1f}s"
        )
    if dns_name:
        return f"DNS lookup for '{dns_name}'"
    service = _WELL_KNOWN_PORTS.get(dport)
    if service:
        return f"{proto.upper()} traffic on port {dport} ({service}), {packet_count} packets over {duration:.1f}s"
    return (
        f"{proto.upper()} traffic on port {dport}, "
        f"{packet_count} packets / {total_bytes} bytes over {duration:.1f}s"
    )


def _flow_signature(proto: str, dport: int, sni: str | None, dns_name: str | None) -> str:
    """A stable identity for a flow *pattern*, deliberately excluding
    volatile per-observation stats (packet/byte counts, duration) that
    make _describe_flow()'s text unique on every single capture. Used
    as semantic_service.analyze()'s cache key so repeat traffic to the
    same host/service is classified by Gemini once, not once per
    capture run.
    """
    if sni:
        return f"tls:{sni}:{dport}"
    if dns_name:
        return f"dns:{dns_name}"
    return f"{proto}:{dport}"


def _flow_key(proto: str, src_ip: str, sport: int, dst_ip: str, dport: int) -> tuple:
    """Both directions of the same connection collapse to one key,
    regardless of which side is the source in a given packet.
    """
    return (proto,) + tuple(sorted([(src_ip, sport), (dst_ip, dport)]))


def extract_flows(pcap_path: str, max_flows: int = 25) -> list[dict[str, Any]]:
    """Read a pcap file and return the top `max_flows` flows by packet
    count, each as {description, protocol, port, packet_count,
    total_bytes, duration_seconds, sni, dns_name}.

    Never raises on bad packet data -- a malformed or truncated packet
    is skipped and logged, since pcap contents are untrusted external
    data, same as any other input this backend accepts.
    """
    try:
        from scapy.all import DNS, IP, TCP, UDP, Raw, rdpcap
    except ImportError as exc:
        raise CaptureUnavailable(
            "scapy is not installed -- run `pip install scapy` to enable pcap analysis."
        ) from exc

    packets = rdpcap(pcap_path)
    flows: dict[tuple, dict[str, Any]] = {}

    for pkt in packets:
        try:
            if IP not in pkt:
                continue
            ip = pkt[IP]
            if TCP in pkt:
                l4, proto = pkt[TCP], "tcp"
            elif UDP in pkt:
                l4, proto = pkt[UDP], "udp"
            else:
                continue

            key = _flow_key(proto, ip.src, int(l4.sport), ip.dst, int(l4.dport))
            ts = float(pkt.time)
            flow = flows.setdefault(key, {
                "proto": proto, "dport": int(l4.dport),
                "packet_count": 0, "total_bytes": 0,
                "first_ts": ts, "last_ts": ts,
                "sni": None, "dns_name": None,
            })
            flow["packet_count"] += 1
            flow["total_bytes"] += len(pkt)
            flow["first_ts"] = min(flow["first_ts"], ts)
            flow["last_ts"] = max(flow["last_ts"], ts)

            if flow["sni"] is None and Raw in pkt and int(l4.dport) == 443:
                flow["sni"] = _extract_sni(bytes(pkt[Raw].load))
            if flow["dns_name"] is None and DNS in pkt and pkt[DNS].qd is not None:
                flow["dns_name"] = pkt[DNS].qd.qname.decode("ascii", errors="ignore").rstrip(".")
        except Exception:
            logger.exception("Skipping unparseable packet in %s", pcap_path)
            continue

    ranked = sorted(flows.values(), key=lambda f: f["packet_count"], reverse=True)[:max_flows]
    results = []
    for f in ranked:
        duration = max(f["last_ts"] - f["first_ts"], 0.001)
        results.append({
            "description": _describe_flow(
                f["proto"], f["dport"], f["sni"], f["dns_name"],
                f["packet_count"], f["total_bytes"], duration,
            ),
            "signature": _flow_signature(f["proto"], f["dport"], f["sni"], f["dns_name"]),
            "protocol": f["proto"],
            "port": f["dport"],
            "packet_count": f["packet_count"],
            "total_bytes": f["total_bytes"],
            "duration_seconds": round(duration, 3),
            "sni": f["sni"],
            "dns_name": f["dns_name"],
        })
    return results
