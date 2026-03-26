import time
import threading

_cache = {}
_lock = threading.Lock()
TTL = 600  # 10 minutes


def put(file_hash: str, df):
    with _lock:
        _cache[file_hash] = (df, time.time())
        cutoff = time.time() - TTL
        for k in [k for k, (_, t) in _cache.items() if t < cutoff]:
            del _cache[k]


def get(file_hash: str):
    with _lock:
        entry = _cache.get(file_hash)
        if entry and time.time() - entry[1] < TTL:
            return entry[0].copy()
    return None


# --- Independent Validation result cache ---

MAX_IV_ENTRIES = 5
_iv_cache: dict[str, tuple[float, dict]] = {}
_iv_lock = threading.Lock()


def put_iv(key: str, data: dict) -> None:
    with _iv_lock:
        _cleanup_iv()
        if len(_iv_cache) >= MAX_IV_ENTRIES:
            oldest_key = min(_iv_cache, key=lambda k: _iv_cache[k][0])
            del _iv_cache[oldest_key]
        _iv_cache[key] = (time.time(), data)


def get_iv(key: str) -> dict | None:
    with _iv_lock:
        _cleanup_iv()
        if key not in _iv_cache:
            return None
        _, data = _iv_cache[key]
        return data


def _cleanup_iv() -> None:
    now = time.time()
    expired = [k for k, (ts, _) in _iv_cache.items() if now - ts > TTL]
    for k in expired:
        del _iv_cache[k]


# --- Temporary ZIP download cache ---

MAX_ZIP_ENTRIES = 5
_zip_cache: dict[str, tuple[float, bytes]] = {}
_zip_lock = threading.Lock()


def put_zip(key: str, data: bytes) -> None:
    with _zip_lock:
        _cleanup_zip()
        if len(_zip_cache) >= MAX_ZIP_ENTRIES:
            oldest = min(_zip_cache, key=lambda k: _zip_cache[k][0])
            del _zip_cache[oldest]
        _zip_cache[key] = (time.time(), data)


def get_zip(key: str) -> bytes | None:
    with _zip_lock:
        _cleanup_zip()
        entry = _zip_cache.pop(key, None)
        return entry[1] if entry else None


def _cleanup_zip() -> None:
    now = time.time()
    for k in [k for k, (ts, _) in _zip_cache.items() if now - ts > TTL]:
        del _zip_cache[k]
