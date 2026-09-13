import ssl
import time
import urllib.request

import psutil

_SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes=25000000"
_SPEED_TEST_TIMEOUT_SECONDS = 8.0
_SPEED_TEST_SAMPLE_BYTES = 2_000_000
_MEASUREMENT_TTL_SECONDS = 30.0
_FALLBACK_BANDWIDTH_MBPS = 10.0
_FALLBACK_LATENCY_MS = 20.0

_cached_bandwidth_mbps = None
_cached_latency_ms = None
_cached_at = 0.0

_last_io_bytes = None
_last_io_timestamp = None


def _build_ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return ssl._create_unverified_context()


_SSL_CONTEXT = _build_ssl_context()


def _measure_real_network():
    try:
        start = time.perf_counter()
        request = urllib.request.Request(_SPEED_TEST_URL, headers={"User-Agent": "NetSentient"})
        response = urllib.request.urlopen(
            request, timeout=_SPEED_TEST_TIMEOUT_SECONDS, context=_SSL_CONTEXT
        )
        first_byte_time = time.perf_counter()
        downloaded_bytes = 0
        while downloaded_bytes < _SPEED_TEST_SAMPLE_BYTES:
            chunk = response.read(65536)
            if not chunk:
                break
            downloaded_bytes += len(chunk)
        end = time.perf_counter()
        response.close()
        latency_ms = (first_byte_time - start) * 1000
        elapsed_seconds = end - first_byte_time
        if elapsed_seconds <= 0 or downloaded_bytes <= 0:
            return _FALLBACK_BANDWIDTH_MBPS, _FALLBACK_LATENCY_MS
        bandwidth_mbps = (downloaded_bytes * 8) / elapsed_seconds / 1_000_000
        return round(bandwidth_mbps, 2), round(latency_ms, 2)
    except Exception:
        return _FALLBACK_BANDWIDTH_MBPS, _FALLBACK_LATENCY_MS


def get_measured_bandwidth():
    global _cached_bandwidth_mbps, _cached_latency_ms, _cached_at
    now = time.time()
    if _cached_bandwidth_mbps is None or (now - _cached_at) > _MEASUREMENT_TTL_SECONDS:
        _cached_bandwidth_mbps, _cached_latency_ms = _measure_real_network()
        _cached_at = now
    return _cached_bandwidth_mbps, _cached_latency_ms


def get_current_throughput_mbps():
    global _last_io_bytes, _last_io_timestamp
    now = time.time()
    counters = psutil.net_io_counters()
    total_bytes = counters.bytes_sent + counters.bytes_recv
    if _last_io_bytes is None or _last_io_timestamp is None:
        _last_io_bytes = total_bytes
        _last_io_timestamp = now
        return 0.0
    elapsed_seconds = now - _last_io_timestamp
    if elapsed_seconds <= 0:
        return 0.0
    delta_bytes = max(0, total_bytes - _last_io_bytes)
    throughput_mbps = (delta_bytes * 8) / elapsed_seconds / 1_000_000
    _last_io_bytes = total_bytes
    _last_io_timestamp = now
    return round(throughput_mbps, 2)