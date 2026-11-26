#!/usr/bin/env python3
"""T22: Cluster load-benchmark baseline script — stresses a running k12 instance
and produces a performance baseline.

Usage (requires fusion-mlx + gateway running, or pointing at a mock):
    FUSION_K12_API_KEY=xxx FUSION_K12_BENCH_TARGET=http://127.0.0.1:11448 \
        python deploy/benchmark.py --duration 60 --concurrency 20

Output: stdout JSON baseline + writes deploy/bench-baseline.json (final artifact)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import httpx
except ImportError:
    print("httpx missing, pip install httpx", file=sys.stderr)
    sys.exit(1)

DEFAULT_TARGET = os.environ.get("FUSION_K12_BENCH_TARGET", "http://127.0.0.1:11448")
API_KEY = os.environ.get("FUSION_K12_API_KEY", "")

# Lightweight endpoints — no LLM dependency, measures the k12 middleware/routing/rate-limit baseline
PROBE_PATHS = ["/api/health", "/api/ready"]


def hit(client: httpx.Client, target: str, path: str) -> tuple[int, float]:
    t0 = time.monotonic()
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        r = client.get(f"{target}{path}", headers=headers, timeout=10)
        return r.status_code, time.monotonic() - t0
    except Exception:
        return 0, time.monotonic() - t0


def run(target: str, duration: int, concurrency: int) -> dict:
    print(f"Benchmark started: target={target} duration={duration}s concurrency={concurrency}", file=sys.stderr)
    results: list[tuple[int, float]] = []
    deadline = time.monotonic() + duration
    idx = 0
    with httpx.Client() as base:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while time.monotonic() < deadline:
                path = PROBE_PATHS[idx % len(PROBE_PATHS)]
                idx += 1
                fut = pool.submit(hit, base, target, path)
                results.append(fut.result())
    lat = [ms for st, ms in results]
    ok = sum(1 for st, _ in results if st == 200)
    fail = len(results) - ok
    base_out = {
        "target": target,
        "duration_s": duration,
        "concurrency": concurrency,
        "total": len(results),
        "ok": ok,
        "fail": fail,
        "rps": round(len(results) / duration, 1),
        "latency_ms": {
            "p50": round(statistics.median(lat) * 1000, 1),
            "p95": round(_percentile(lat, 0.95) * 1000, 1),
            "p99": round(_percentile(lat, 0.99) * 1000, 1),
            "max": round(max(lat) * 1000, 1),
        },
        "error_rate": round(fail / max(1, len(results)), 4),
    }
    return base_out


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = int(len(s) * p)
    return s[min(k, len(s) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser(description="k12 cluster load-benchmark baseline")
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()
    out = run(args.target, args.duration, args.concurrency)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    out_path = os.path.join(os.path.dirname(__file__), "bench-baseline.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nBaseline written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
