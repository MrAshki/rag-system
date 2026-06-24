import time
from collections import defaultdict
from threading import Lock
from flask import jsonify

_calls = defaultdict(list)
_lock = Lock()


def check_rate_limit(key: str, min_interval_seconds: float, max_per_window: int, window_seconds: int):
    """Returns None if allowed, or an error message string if rate-limited.
    In-memory only (single-process) — fine for one Flask worker; swap for a
    shared store (e.g. Redis) if scaling to multiple worker processes."""
    now = time.time()
    with _lock:
        history = _calls[key]
        history[:] = [t for t in history if now - t < window_seconds]

        if history and now - history[-1] < min_interval_seconds:
            return "درخواست‌های شما خیلی سریع است، کمی صبر کنید."
        if len(history) >= max_per_window:
            return "تعداد درخواست‌های شما در این بازه زمانی زیاد بوده است."

        history.append(now)
        return None


def rate_limited(key_func, min_interval_seconds=2, max_per_window=30, window_seconds=600):
    def decorator(view):
        def wrapped(*args, **kwargs):
            key = key_func()
            error = check_rate_limit(key, min_interval_seconds, max_per_window, window_seconds)
            if error:
                return jsonify({"error": error}), 429
            return view(*args, **kwargs)
        wrapped.__name__ = view.__name__
        return wrapped
    return decorator
