"""pytest 全局 fixture + live-LLM 用例门控。"""

from __future__ import annotations

import os

import pytest

# P2: CI (ubuntu-latest, 无 fusion-mlx) 直连真实 LLM 必失败/降级。
# live 用例默认在无 FUSION_K12_LIVE_TESTS=1 时 skip; 本机需真实加载模型时显式开启。
_LIVE_ENABLED = os.environ.get("FUSION_K12_LIVE_TESTS", "") == "1"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: 需 fusion-mlx 真实加载模型的用例")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # P2: 未显式开启 live 时, 标 live 的用例 skip; 避免误标漏标。
    skip_live = pytest.mark.skip(reason="需 fusion-mlx 运行 (设 FUSION_K12_LIVE_TESTS=1 开启)")
    for item in items:
        if "live" in item.keywords and not _LIVE_ENABLED:
            item.add_marker(skip_live)
