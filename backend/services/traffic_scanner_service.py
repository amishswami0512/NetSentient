"""Scan the local machine's active internet connections with psutil."""
from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import psutil

from config import SUPPORTED_TRAFFIC_TYPES
from services.state_service import state

_SCAN_LIMIT = 40
_DNS_TIMEOUT_SECONDS = 0.75
_VIDEO_HOST_HINTS = ("googlevideo", "youtube", "zoom", "teams", "meet", "twitch", "discord", "webex")
_VIDEO_PROCESS_HINTS = ("zoom", "teams", "webex", "discord", "meet")
_FILE_PORTS = {20, 21, 22, 989, 990}
_REALTIME_PORTS = {3478, 3479, 5349, 5350}


def _process_name(pid: int | None) -> str:
    if not pid:
        return "unknown_process"
    try:
        return psutil.Process(pid).name() or "unknown_process"
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "unknown_process"


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror, socket.gaierror):
        return ip


def _infer_type(process: str, hostname: str, remote_port: int) -> str:
    process_lower = process.lower()
    host_lower = hostname.lower()
    if any(hint in host_lower for hint in _VIDEO_HOST_HINTS) or any(
        hint in process_lower for hint in _VIDEO_PROCESS_HINTS
    ):
        return "video"
    if remote_port in _REALTIME_PORTS:
        return "real_time"
    if remote_port in _FILE_PORTS:
        return "file"
    return "background"


def scan_active_connections() -> list[dict[str, Any]]:
    """Read established TCP/UDP internet connections and add them to state.

    The scanner does not claim to know application semantics from a socket.
    It uses conservative process/host/port hints to choose a traffic tier,
    then the normal NetSentient semantic/priority pipeline handles the label.
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for conn in connections:
        if not conn.raddr:
            continue
        is_established_tcp = conn.status in (psutil.CONN_ESTABLISHED, "ESTABLISHED")
        is_active_udp = conn.type == socket.SOCK_DGRAM and conn.status in (psutil.CONN_NONE, "NONE", None)
        if not (is_established_tcp or is_active_udp):
            continue
        dedupe_key = (
            conn.pid,
            conn.laddr.ip if conn.laddr else None,
            conn.laddr.port if conn.laddr else None,
            conn.raddr.ip,
            conn.raddr.port,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        remote_ip = conn.raddr.ip
        remote_port = conn.raddr.port
        candidates.append(
            {
                "pid": conn.pid,
                "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else None,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "status": conn.status,
                "process_name": _process_name(conn.pid),
            }
        )

    # Keep the scan useful and responsive on machines with hundreds of sockets.
    candidates = candidates[:_SCAN_LIMIT]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_hostname, item["remote_ip"]): item for item in candidates}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item["remote_hostname"] = future.result(timeout=_DNS_TIMEOUT_SECONDS)
            except Exception:
                item["remote_hostname"] = item["remote_ip"]

    # A scan represents a fresh snapshot, not a history of every connection
    # ever observed. Replace only the previous scan entries.
    state.clear_scanned_traffic()

    scanned: list[dict[str, Any]] = []
    for item in candidates:
        process = item["process_name"]
        hostname = item.get("remote_hostname", item["remote_ip"])
        traffic_type = _infer_type(process, hostname, item["remote_port"])
        label = (
            f"{process} connection to {hostname} on port {item['remote_port']}"
        )

        entry = state.add_traffic(
            traffic_type,
            label,
            metadata={
                "source_kind": "local_scan",
                "process_name": process,
                "pid": item["pid"],
                "local_address": item["local_address"],
                "remote_ip": item["remote_ip"],
                "remote_hostname": hostname,
                "remote_port": item["remote_port"],
                "connection_status": item["status"],
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        scanned.append(entry)

    return scanned
