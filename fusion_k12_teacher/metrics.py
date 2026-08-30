"""Prometheus 风格指标 — v2.0 M3-T16。

stdlib 实现 (零外部依赖): 计数器 + 直方图 + gauge, 线程安全。
/api/metrics 输出 Prometheus exposition format。
6 核心指标 (§4.5):
  k12_request_total{route,status}
  k12_request_duration_seconds{route} (histogram)
  k12_llm_call_total{model,status}
  k12_llm_duration_seconds (histogram)
  k12_active_jobs (gauge)
  k12_db_pool_inuse (gauge)
"""

from __future__ import annotations

import threading

# 直方图桶 (秒) — 覆盖 10ms~30s
_HIST_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class _Counter:
    """带 label 的计数器。"""

    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()):
        self.name = name
        self.help = help
        self._labels = labels
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, **labels) -> None:
        key = tuple(labels.get(lbl, "") for lbl in self._labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + 1.0

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            for key, val in sorted(self._values.items()):
                label_str = ",".join(
                    f'{lbl}="{k}"' for lbl, k in zip(self._labels, key) if self._labels
                )
                if label_str:
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return "\n".join(lines)


class _Histogram:
    """直方图 — 累计桶计数 + 总和 + 计数。"""

    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()):
        self.name = name
        self.help = help
        self._labels = labels
        # per-label-set: [bucket_counts list, sum, count]
        self._data: dict[tuple, list] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels) -> None:
        key = tuple(labels.get(lbl, "") for lbl in self._labels)
        with self._lock:
            d = self._data.get(key)
            if d is None:
                d = [[0.0] * len(_HIST_BUCKETS), 0.0, 0.0]
                self._data[key] = d
            for i, b in enumerate(_HIST_BUCKETS):
                if value <= b:
                    d[0][i] += 1.0
            d[1] += value
            d[2] += 1.0

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, d in sorted(self._data.items()):
                label_base = ",".join(
                    f'{lbl}="{k}"' for lbl, k in zip(self._labels, key) if self._labels
                )
                counts, total, count = d
                for i, b in enumerate(_HIST_BUCKETS):
                    le = f'le="{b}"'
                    lbl = f"{label_base},{le}" if label_base else le
                    lines.append(f'{self.name}_bucket{{{lbl}}} {counts[i]}')
                inf_lbl = f"{label_base},le=\"+Inf\"" if label_base else 'le="+Inf"'
                lines.append(f'{self.name}_bucket{{{inf_lbl}}} {count}')
                if label_base:
                    lines.append(f"{self.name}_sum{{{label_base}}} {total}")
                    lines.append(f"{self.name}_count{{{label_base}}} {count}")
                else:
                    lines.append(f"{self.name}_sum {total}")
                    lines.append(f"{self.name}_count {count}")
        return "\n".join(lines)


class _Gauge:
    """带 label 的仪表。"""

    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()):
        self.name = name
        self.help = help
        self._labels = labels
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels) -> None:
        key = tuple(labels.get(lbl, "") for lbl in self._labels)
        with self._lock:
            self._values[key] = float(value)

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for key, val in sorted(self._values.items()):
                label_str = ",".join(
                    f'{lbl}="{k}"' for lbl, k in zip(self._labels, key) if self._labels
                )
                if label_str:
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return "\n".join(lines)


class MetricsRegistry:
    """指标注册表 — 6 核心指标 + render Prometheus exposition format。"""

    def __init__(self):
        self.request_total = _Counter(
            "k12_request_total", "Total HTTP requests", ("route", "status")
        )
        self.request_duration = _Histogram(
            "k12_request_duration_seconds", "HTTP request latency", ("route",)
        )
        self.llm_call_total = _Counter(
            "k12_llm_call_total", "Total LLM calls", ("model", "status")
        )
        self.llm_duration = _Histogram(
            "k12_llm_duration_seconds", "LLM call latency", ()
        )
        self.active_jobs = _Gauge(
            "k12_active_jobs", "In-flight scheduled tasks", ()
        )
        self.db_pool_inuse = _Gauge(
            "k12_db_pool_inuse", "DB connections in use", ()
        )

    def record_request(self, route: str, status_code: int, duration_s: float) -> None:
        self.request_total.inc(route=route, status=str(status_code))
        self.request_duration.observe(duration_s, route=route)

    def record_llm(self, model: str, ok: bool, duration_s: float) -> None:
        self.llm_call_total.inc(model=model, status="ok" if ok else "error")
        self.llm_duration.observe(duration_s)

    def set_active_jobs(self, n: int) -> None:
        self.active_jobs.set(n)

    def set_db_pool_inuse(self, n: int) -> None:
        self.db_pool_inuse.set(n)

    def render(self) -> str:
        parts = [
            self.request_total.render(),
            self.request_duration.render(),
            self.llm_call_total.render(),
            self.llm_duration.render(),
            self.active_jobs.render(),
            self.db_pool_inuse.render(),
        ]
        return "\n".join(parts) + "\n"


_registry: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    """单例指标注册表。"""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


def render_prometheus() -> str:
    """输出 Prometheus exposition format 文本。"""
    return get_metrics().render()
