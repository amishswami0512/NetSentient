"""Fast-path cache for common/repeated traffic payloads.

Re-running full classification (and, later, priority scoring) on a
payload we've already seen is wasted work -- especially with an
external AI call in the mix (GeminiClassifier) or a heavier model
pipeline down the line. This cache sits in front of that work:

- A small set of common/expected payloads (demo default labels,
  frequently-typed inputs) is pre-seeded so they resolve instantly on
  the very first request, with no model call at all.
- Any other payload is classified normally the first time, then
  memoized here so repeat lookups (within this process's lifetime)
  are instant too.

Purely a cache, not a shortcut around correctness: a hit returns
exactly what full classification would have returned for that same
(normalized) text, so it never introduces nondeterminism -- it only
skips redundant work.
"""
from collections import OrderedDict
from typing import Any


class PayloadCache:
    def __init__(self, max_entries: int = 512) -> None:
        self._max_entries = max_entries
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    def get(self, text: str) -> dict[str, Any] | None:
        key = self._normalize(text)
        result = self._store.get(key)
        if result is None:
            return None
        self._store.move_to_end(key)
        return dict(result)

    def put(self, text: str, result: dict[str, Any]) -> None:
        key = self._normalize(text)
        self._store[key] = dict(result)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def seed(self, entries: dict[str, dict[str, Any]]) -> None:
        for text, result in entries.items():
            self.put(text, result)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, text: str) -> bool:
        return self._normalize(text) in self._store
