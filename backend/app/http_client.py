"""Resilient HTTP client for live feeds.

Design rules learned the hard way for a live demo:
  * every call is time-boxed, so the UI never hangs on bad wifi;
  * successful responses are cached on disk with a TTL;
  * on failure we fall back to the last good cache, then to a bundled snapshot;
  * every result carries provenance so the UI can be honest about freshness.

Uses only the standard library, so the backend runs with zero pip installs.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from . import config

_LOCK = threading.Lock()
_MEMORY: Dict[str, Tuple[float, Any]] = {}

# Provenance values surfaced to the frontend.
LIVE = "live"
CACHE = "cache"
SNAPSHOT = "offline-snapshot"
UNAVAILABLE = "unavailable"

_snapshot_cache: Optional[dict] = None
_status: Dict[str, Dict[str, Any]] = {}


def _cache_path(key: str):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return config.CACHE_DIR / f"{digest}.json"


def load_snapshot() -> dict:
    global _snapshot_cache
    if _snapshot_cache is None:
        try:
            with open(config.SNAPSHOT_FILE, "r", encoding="utf-8") as fh:
                _snapshot_cache = json.load(fh)
        except Exception:
            _snapshot_cache = {}
    return _snapshot_cache


def feed_status() -> Dict[str, Dict[str, Any]]:
    """Per-feed health, surfaced at /api/system/status."""
    with _LOCK:
        return {k: dict(v) for k, v in _status.items()}


def _record(feed: str, provenance: str, detail: str = "") -> None:
    with _LOCK:
        _status[feed] = {
            "provenance": provenance,
            "detail": detail,
            "checked_at": time.time(),
        }


def build_url(base: str, params: Dict[str, Any]) -> str:
    if not params:
        return base
    return base + "?" + urllib.parse.urlencode(params, doseq=True)


def get_json(
    url: str,
    *,
    feed: str,
    ttl: int,
    snapshot_key: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Tuple[Any, str]:
    """Fetch JSON. Returns (payload, provenance).

    Never raises for network problems -- callers always get something usable.
    """
    now = time.time()
    timeout = timeout or config.HTTP_TIMEOUT

    # 1. Fresh in-memory cache.
    with _LOCK:
        hit = _MEMORY.get(url)
    if hit and now - hit[0] < ttl:
        _record(feed, CACHE, "memory cache")
        return hit[1], CACHE

    # 2. Fresh on-disk cache (survives restarts -- important for demos).
    disk = _read_disk(url)
    if disk and now - disk[0] < ttl:
        with _LOCK:
            _MEMORY[url] = (disk[0], disk[1])
        _record(feed, CACHE, "disk cache")
        return disk[1], CACHE

    # 3. Live fetch, unless explicitly running offline.
    if not config.OFFLINE:
        payload = _fetch(url, timeout)
        if payload is not None:
            with _LOCK:
                _MEMORY[url] = (now, payload)
            _write_disk(url, now, payload)
            _record(feed, LIVE, "fetched")
            return payload, LIVE

    # 4. Stale cache beats no data.
    if disk:
        age_min = int((now - disk[0]) / 60)
        _record(feed, CACHE, f"stale cache ({age_min} min old)")
        return disk[1], CACHE

    # 5. Bundled snapshot so the product still demonstrates end to end.
    if snapshot_key:
        snap = load_snapshot().get(snapshot_key)
        if snap is not None:
            _record(feed, SNAPSHOT, "bundled snapshot")
            return snap, SNAPSHOT

    _record(feed, UNAVAILABLE, "no data")
    return None, UNAVAILABLE


def _fetch(url: str, timeout: float) -> Optional[Any]:
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    for attempt in range(config.HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if attempt >= config.HTTP_RETRIES:
                return None
            time.sleep(0.4)
    return None


def _read_disk(url: str) -> Optional[Tuple[float, Any]]:
    path = _cache_path(url)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        return float(blob["ts"]), blob["payload"]
    except Exception:
        return None


def _write_disk(url: str, ts: float, payload: Any) -> None:
    try:
        with open(_cache_path(url), "w", encoding="utf-8") as fh:
            json.dump({"ts": ts, "url": url, "payload": payload}, fh)
    except Exception:
        pass


def worst_provenance(*values: str) -> str:
    """Combine provenance flags -- the least fresh one wins."""
    order = [LIVE, CACHE, SNAPSHOT, UNAVAILABLE]
    worst = LIVE
    for v in values:
        if v in order and order.index(v) > order.index(worst):
            worst = v
    return worst
