"""
pipeline/timing.py
-------------------
Lightweight per-stage timing utility. Wrap any pipeline function with @timed("stage_name")
and call get_timing_report() / reset_timing() around a single document's processing.
"""

import time
import functools
import threading

_local = threading.local()


def _get_log():
    if not hasattr(_local, "log"):
        _local.log = []
    return _local.log


def reset_timing():
    """Call this at the start of processing one document."""
    _local.log = []


def timed(stage_name: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                _get_log().append({"stage": stage_name, "seconds": round(elapsed, 4)})
        return wrapper
    return decorator


def get_timing_report() -> list[dict]:
    """Call this after processing one document to get the per-stage breakdown."""
    return list(_get_log())


def print_timing_report():
    log = get_timing_report()
    if not log:
        print("[TIMING] No stages recorded.")
        return
    total = sum(e["seconds"] for e in log)
    print("\n[TIMING] Per-stage breakdown:")
    for entry in log:
        pct = (entry["seconds"] / total * 100) if total else 0
        print(f"  {entry['stage']:30s} {entry['seconds']:8.3f}s  ({pct:5.1f}%)")
    print(f"  {'TOTAL':30s} {total:8.3f}s")