"""Background thread: periodically scans real live network connections
(services/network_scan_service.py) and adds newly-seen ones as traffic,
so opening a new site or app shows up in the dashboard on its own --
no need to call POST /api/traffic/scan by hand every time.

Dedup is by exact label match against currently active traffic (the
label -- "chrome connection to youtube.com on port 443" -- has no
volatile per-observation stats baked in, unlike capture_service.py's
pcap flow descriptions, so an exact match reliably means "already
tracked", not just "looks similar").

A single failed scan cycle (DNS hiccup, psutil permission error, a
Gemini call failing) never kills the loop or the app -- it's a daemon
thread that just tries again next interval.
"""
import logging
import threading
import time

from config import Config
from services import network_scan_service
from services.state_service import state

logger = logging.getLogger(__name__)

_started = False
_start_lock = threading.Lock()


def _already_tracked(label: str) -> bool:
    return any(t["label"] == label for t in state.get_traffic_list())


def poll_once() -> int:
    """Runs one scan cycle, adds any genuinely new connections as
    traffic, and returns how many were added. Exposed as its own
    function (not just folded into the loop) so it can be called
    directly -- from a test, or from a route that wants an immediate
    scan instead of waiting for the next tick.
    """
    added = 0
    for connection in network_scan_service.scan_active_connections():
        label = connection["label"]
        if _already_tracked(label):
            continue
        try:
            state.add_captured_traffic(label)
            added += 1
        except Exception:
            logger.exception("Failed to add scanned connection as traffic: %s", label)
    return added


def _run_forever() -> None:
    while True:
        try:
            poll_once()
        except Exception:
            logger.exception("Background connection scan cycle failed")
        time.sleep(Config.SCAN_POLL_INTERVAL_SECONDS)


def start() -> None:
    """Idempotent and safe to call from every worker/reloader process
    that imports this module -- only the first call in a given process
    actually starts the thread.
    """
    global _started
    with _start_lock:
        if _started or not Config.SCAN_POLL_ENABLED:
            return
        _started = True
    thread = threading.Thread(target=_run_forever, name="scan-poller", daemon=True)
    thread.start()
    logger.info(
        "Background connection scan started (every %.0fs)", Config.SCAN_POLL_INTERVAL_SECONDS
    )
