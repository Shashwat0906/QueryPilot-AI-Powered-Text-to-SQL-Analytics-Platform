"""Bounded in-memory result cache (LRU + TTL).

Key = SHA-256 of:
    normalized question | database identity | schema version |
    provider | model | prompt version | answer mode | max rows | user/auth scope

so a cached answer is only reused when *everything* that could change it is
identical. Changing the schema changes `schema_version`, so old entries can no
longer match; `invalidate_schema()` additionally deletes them right away.

Policy:
* Only successful, validated, read-only results are stored (the caller
  enforces this; failures are never passed to `set`).
* Results containing sensitive columns (email, phone, ...) are not stored.
* Bounded: at most `max_entries`, least-recently-used evicted first.
* Entries expire after `ttl_seconds`.

Limitations (by design for v1): the cache lives in this process only - it is
lost on restart and not shared between multiple app instances. A shared cache
(e.g. Redis) would be the next step for horizontal scaling.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable


def normalize_question(question: str) -> str:
    """'  What is our TOTAL revenue?? ' -> 'what is our total revenue'"""
    text = question.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[?.!\s]+$", "", text)


@dataclass
class _Entry:
    value: Any
    expires_at: float
    schema_version: str


class QueryCache:
    def __init__(self, *, enabled: bool, ttl_seconds: int, max_entries: int,
                 sensitive_columns: list[str], clock: Callable[[], float] = time.monotonic):
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.sensitive_columns = {c.lower() for c in sensitive_columns}
        self._clock = clock
        self._data: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.skipped_sensitive = 0

    @staticmethod
    def make_key(*, question: str, database_id: str, schema_version: str, provider: str,
                 model: str, max_rows: int, scope: str = "anonymous", prompt_version: str = "",
                 answer_mode: str = "") -> str:
        material = json.dumps(
            {
                "q": normalize_question(question),
                "db": database_id,
                "schema": schema_version,
                "provider": provider,
                "model": model,
                "prompt": prompt_version,
                "answer_mode": answer_mode,
                "max_rows": max_rows,
                "scope": scope,
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at <= self._clock():
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)  # mark as recently used
            self.hits += 1
            return copy.deepcopy(entry.value)

    def is_sensitive(self, column_names: list[str]) -> bool:
        return any(name.lower() in self.sensitive_columns for name in column_names)

    def set(self, key: str, value: Any, *, schema_version: str, column_names: list[str]) -> bool:
        """Store a successful result. Returns False if it was not cached."""
        if not self.enabled:
            return False
        if self.is_sensitive(column_names):
            self.skipped_sensitive += 1
            return False
        with self._lock:
            self._data[key] = _Entry(copy.deepcopy(value), self._clock() + self.ttl_seconds, schema_version)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)  # evict least recently used
        return True

    def invalidate_schema(self, old_version: str, new_version: str | None = None) -> int:  # noqa: ARG002
        """Drop every entry built against `old_version` of the schema."""
        with self._lock:
            stale = [k for k, e in self._data.items() if e.schema_version == old_version]
            for key in stale:
                del self._data[key]
        return len(stale)

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
        return count

    def stats(self) -> dict[str, Any]:
        lookups = self.hits + self.misses
        with self._lock:
            size = len(self._data)
        return {
            "enabled": self.enabled,
            "entries": size,
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl_seconds,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / lookups, 4) if lookups else None,
            "skipped_sensitive": self.skipped_sensitive,
        }
