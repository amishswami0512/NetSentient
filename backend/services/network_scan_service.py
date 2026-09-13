"""Reads real live network connections off this machine and turns each
into a factual description -- same philosophy as capture_service.py's
pcap ingestion. This module never guesses a category itself; the
description (process name + hostname + port) goes through the same
semantic_service pipeline everything else does, so "youtube.com" gets
classified as video because Gemini (or the fallback classifier)
actually recognizes it, not because port 443 is hardcoded to mean
"video" regardless of what's actually being connected to.
"""
import socket

import psutil

from services import live_sniff_service

# Reverse DNS (socket.gethostbyaddr) has no per-call timeout knob, and
# this function is now called repeatedly from a background poller
# (services/scan_poller.py), not just an occasional manual click -- an
# unresponsive resolver must not be able to stall it indefinitely.
# setdefaulttimeout is process-global, not scoped to this call alone;
# an acceptable, documented tradeoff given how briefly it's held here.
_DNS_TIMEOUT_SECONDS = 1.0


def _resolve_hostname(ip: str) -> str:
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT_SECONDS)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ip
    finally:
        socket.setdefaulttimeout(None)


def scan_active_connections(limit: int = 10) -> list[dict[str, str]]:
    results = []
    seen = set()
    for connection in psutil.net_connections(kind="inet"):
        if connection.status != psutil.CONN_ESTABLISHED:
            continue
        if connection.raddr is None:
            continue
        remote_ip, remote_port = connection.raddr
        key = (remote_ip, remote_port)
        if key in seen:
            continue
        seen.add(key)
        process_name = "unknown_process"
        if connection.pid:
            try:
                process_name = psutil.Process(connection.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = "unknown_process"
        # A live-sniffed SNI hostname (the actual site the connection
        # declared itself as, straight from the TLS handshake) beats
        # reverse DNS whenever we have one -- reverse DNS is unreliable
        # for exactly the sites worth naming correctly (Google-hosted
        # services all resolve to generic "*.1e100.net" infrastructure
        # names, not "youtube.com").
        hostname = live_sniff_service.get_sni_for(remote_ip, remote_port) or _resolve_hostname(remote_ip)
        label = f"{process_name} connection to {hostname} on port {remote_port}"
        results.append({"label": label, "hostname": hostname, "port": str(remote_port)})
        if len(results) >= limit:
            break
    return results
