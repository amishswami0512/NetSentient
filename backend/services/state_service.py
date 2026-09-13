"""SQLite-persisted state manager.

Holds all mutable demo state (active traffic, congestion flag, semantic
routing flag, ID counters) behind one object instead of scattering
module-level globals across the codebase.

Backed by a real SQLite database (Config.STATE_DB_PATH, WAL mode) --
transactional writes, safe to share across multiple processes (e.g.
gunicorn workers) reading/writing the same file, and unaffected by a
restart. This replaced an earlier whole-file-JSON-overwrite approach:
same public API, so no route or other service needed to change.

Use POST /api/simulation/reset or POST /api/demo/reset to get back to
a clean slate without restarting the server.
"""
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from config import Config
from services import priority_service, semantic_service

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    priority REAL NOT NULL,
    priority_factors TEXT NOT NULL,
    low_confidence INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DEFAULT_KV = {
    "congestion": "0",
    "semantic_routing_enabled": "1",
    "traffic_seq": "0",
    "simulation_seq": "0",
}


class StateService:
    def __init__(self) -> None:
        # sqlite3 connections aren't safe for concurrent use from
        # multiple threads without external synchronization even with
        # check_same_thread=False -- this lock serializes writes
        # within this process. Reads don't need it: SQLite handles
        # concurrent readers on its own, and WAL mode lets readers
        # proceed even while a write is in progress.
        self._lock = threading.Lock()

        db_path = Path(Config.STATE_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        with self._lock:
            for key, default in _DEFAULT_KV.items():
                self._conn.execute("INSERT OR IGNORE INTO kv_state (key, value) VALUES (?, ?)", (key, default))
            self._conn.commit()

    # -- kv helpers ------------------------------------------------------
    def _get_kv(self, key: str) -> str:
        row = self._conn.execute("SELECT value FROM kv_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else _DEFAULT_KV[key]

    def _set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM traffic")
            for key, default in _DEFAULT_KV.items():
                self._conn.execute(
                    "INSERT INTO kv_state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, default),
                )
            self._conn.commit()

    # -- traffic -----------------------------------------------------
    def _next_traffic_id(self) -> tuple[str, int]:
        seq = int(self._get_kv("traffic_seq")) + 1
        self._set_kv("traffic_seq", str(seq))
        return f"traffic-{seq:03d}", seq

    def _insert_traffic(
        self, traffic_id: str, seq: int, traffic_type: str, label: str,
        scored: dict[str, Any], factors: dict[str, float], source: str,
    ) -> dict[str, Any]:
        entry = {
            "id": traffic_id,
            "type": traffic_type,
            "label": label,
            "priority": scored["priority"],
            "priority_factors": factors,
            "low_confidence": scored["low_confidence"],
            "source": source,
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO traffic "
                "(id, type, label, priority, priority_factors, low_confidence, source, created_seq) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    traffic_id, traffic_type, label, scored["priority"],
                    json.dumps(factors), int(scored["low_confidence"]), source, seq,
                ),
            )
            self._conn.commit()
        return entry

    def add_traffic(self, traffic_type: str, label: str) -> dict[str, Any]:
        """Create a traffic item, with priority computed from the label's
        actual semantic content (not just a flat per-type lookup).

        `traffic_type` (client-declared, already validated against
        SUPPORTED_TRAFFIC_TYPES) is used as the category for priority
        safety-bounds purposes; the label text is what's semantically
        analyzed (via Gemini, or the deterministic fallback) to get the
        urgency/consequence/latency/reliability factors that actually
        differentiate priority within that category.
        """
        traffic_id, seq = self._next_traffic_id()
        analysis = semantic_service.analyze_for_category(label, traffic_type)
        scored = priority_service.score(traffic_type, analysis["confidence"], analysis["factors"])
        return self._insert_traffic(traffic_id, seq, traffic_type, label, scored, analysis["factors"], analysis["source"])

    def add_captured_traffic(self, label: str, cache_key: str | None = None) -> dict[str, Any]:
        """Like add_traffic(), but for real captured traffic (see
        services/capture_service.py) where the category isn't known in
        advance. Uses semantic_service.analyze() -- Gemini's own
        category guess is trusted here, unlike add_traffic() where a
        client-declared type takes precedence.

        `cache_key`, when given, should be the flow's stable signature
        (capture_service's `signature` field, not its `description`) --
        see semantic_service.analyze()'s docstring for why.
        """
        traffic_id, seq = self._next_traffic_id()
        analysis = semantic_service.analyze(label, cache_key=cache_key)
        scored = priority_service.score(analysis["category"], analysis["confidence"], analysis["factors"])
        return self._insert_traffic(traffic_id, seq, analysis["category"], label, scored, analysis["factors"], analysis["source"])

    def get_traffic_list(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, type, label, priority, priority_factors, low_confidence, source "
            "FROM traffic ORDER BY created_seq"
        ).fetchall()
        return [
            {
                "id": r[0], "type": r[1], "label": r[2], "priority": r[3],
                "priority_factors": json.loads(r[4]), "low_confidence": bool(r[5]), "source": r[6],
            }
            for r in rows
        ]

    def clear_traffic(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM traffic")
            self._conn.commit()

    # -- congestion ----------------------------------------------------
    def set_congestion(self, enabled: bool) -> None:
        self._set_kv("congestion", "1" if enabled else "0")

    def get_congestion(self) -> bool:
        return self._get_kv("congestion") == "1"

    # -- semantic routing ----------------------------------------------
    def set_semantic_routing(self, enabled: bool) -> None:
        self._set_kv("semantic_routing_enabled", "1" if enabled else "0")

    def get_semantic_routing(self) -> bool:
        return self._get_kv("semantic_routing_enabled") == "1"

    # -- simulation ------------------------------------------------------
    def next_simulation_id(self) -> str:
        seq = int(self._get_kv("simulation_seq")) + 1
        self._set_kv("simulation_seq", str(seq))
        return f"sim-{seq:03d}"


# Single shared instance used across routes/services for this process.
state = StateService()
