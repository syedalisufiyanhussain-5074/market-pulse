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
