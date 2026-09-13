"""Best-effort real network measurements for the local machine.

The prototype's routing load remains simulated, but bandwidth and HTTP
latency are measured from the machine running Flask. Measurements are cached
briefly so a dashboard refresh does not trigger a download every time.
"""
from __future__ import annotations

import time
import urllib.request
from threading import Lock
from typing import Any

from config import Config


_measurement_lock = Lock()
_cached_measurement: dict[str, Any] | None = None
_cached_at = 0.0


def _measure() -> dict[str, Any]:
    """Download a small public sample and calculate throughput + latency."""
    started = time.perf_counter()
    request = urllib.request.Request(
        Config.SPEED_TEST_URL,
        headers={"User-Agent": "NetSentient/1.0 network measurement"},
    )

    bytes_read = 0
    with urllib.request.urlopen(request, timeout=Config.SPEED_TEST_TIMEOUT_SECONDS) as response:
        first_byte_ms = (time.perf_counter() - started) * 1000
        while bytes_read < Config.SPEED_TEST_MAX_BYTES:
            chunk = response.read(min(64 * 1024, Config.SPEED_TEST_MAX_BYTES - bytes_read))
            if not chunk:
                break
            bytes_read += len(chunk)

    elapsed = max(time.perf_counter() - started, 0.001)
    bandwidth_mbps = (bytes_read * 8) / elapsed / 1_000_000
    return {
        "bandwidth_mbps": round(max(0.01, bandwidth_mbps), 2),
        "latency_ms": round(max(1.0, first_byte_ms), 1),
        "measurement_source": Config.SPEED_TEST_URL,
        "measured_bytes": bytes_read,
        "measured_at": time.time(),
        "measurement_ok": True,
    }


def get_network_measurement(force_refresh: bool = False) -> dict[str, Any]:
    """Return a cached real measurement, with a safe deterministic fallback."""
    global _cached_measurement, _cached_at

    now = time.time()
    with _measurement_lock:
        if (
            not force_refresh
            and _cached_measurement is not None
            and now - _cached_at < Config.SPEED_TEST_CACHE_SECONDS
        ):
            return dict(_cached_measurement)

        try:
            measurement = _measure()
        except Exception:
            measurement = {
                "bandwidth_mbps": Config.SPEED_TEST_FALLBACK_BANDWIDTH_MBPS,
                "latency_ms": Config.SPEED_TEST_FALLBACK_LATENCY_MS,
                "measurement_source": "fallback",
                "measured_bytes": 0,
                "measured_at": now,
                "measurement_ok": False,
            }

        _cached_measurement = measurement
        _cached_at = now
        return dict(measurement)


def clear_measurement_cache() -> None:
    global _cached_measurement, _cached_at
    with _measurement_lock:
        _cached_measurement = None
        _cached_at = 0.0
