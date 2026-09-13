import socket

import psutil

_PORT_CATEGORY_HINTS = {
    22: "background",
    53: "background",
    80: "file",
    123: "background",
    443: "video",
    3389: "real_time",
    5060: "voice_chat",
}

_DEFAULT_CATEGORY = "background"


def _resolve_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ip


def _guess_category(remote_port):
    return _PORT_CATEGORY_HINTS.get(remote_port, _DEFAULT_CATEGORY)


def scan_active_connections(limit=10):
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
        hostname = _resolve_hostname(remote_ip)
        category = _guess_category(remote_port)
        label = f"{process_name} connection to {hostname} on port {remote_port}"
        results.append({"type": category, "label": label})
        if len(results) >= limit:
            break
    return results