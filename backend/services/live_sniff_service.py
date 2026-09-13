"""Live TLS SNI sniffing: watches real outbound HTTPS handshakes on a
network interface and remembers which hostname each (ip, port) pair
was actually talking to -- the same unencrypted ClientHello field
capture_service.py already reads from recorded pcaps, just read live
instead of from a file.

This exists because reverse DNS (network_scan_service.py's original
approach) is unreliable for exactly the sites you'd most want
classified correctly: YouTube, Gmail, and most Google-hosted services
all reverse-resolve to generic infrastructure hostnames like
"ia-in-f91.1e100.net", not "youtube.com" -- confirmed by testing
against Google's own real IPs, not assumed. SNI sniffing sidesteps
that entirely: it reads what the browser itself declared it was
connecting to, straight out of the handshake.

Needs to actually see raw packets on a real interface, which needs
root/CAP_NET_RAW (same requirement as `tcpdump`) -- off by default
(Config.SNI_SNIFF_ENABLED), and a missing scapy or missing privilege
degrades to "SNI sniffing unavailable" logging, never a crash. When
it's off or unavailable, network_scan_service.py falls back to its
original reverse-DNS behavior exactly as before this existed.
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

_started = False
_start_lock = threading.Lock()


def get_sni_for(ip: str, port: int) -> str | None:
    """Never raises, never blocks -- a plain dict read. Safe to call
    regardless of whether sniffing is enabled, running, or supported
    on this platform at all.
    """
    with _cache_lock:
        return _sni_cache.get((ip, port))


def _record_sni(pkt: Any) -> None:
    from services.capture_service import _extract_sni  # reuse, don't duplicate

    try:
        from scapy.all import IP, TCP, Raw
    except ImportError:
        return

    try:
        if IP not in pkt or TCP not in pkt or Raw not in pkt:
            return
        if int(pkt[TCP].dport) != 443:
            return  # only ClientHellos (client -> server) carry the SNI we want
        sni = _extract_sni(bytes(pkt[Raw].load))
        if not sni:
            return
        key = (pkt[IP].dst, int(pkt[TCP].dport))
        with _cache_lock:
            _sni_cache[key] = sni
            _sni_cache.move_to_end(key)
            while len(_sni_cache) > _MAX_ENTRIES:
                _sni_cache.popitem(last=False)
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
        sniff(iface=interface, filter="tcp port 443", prn=_record_sni, store=False)
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
