"""A12: 引擎异常分类层 — 区分可降级与不可降级, 后者必须上抛。

引擎原 blanket `except Exception` 统一降级返默认 dataclass, 把配置错/认证错
(LLM 侧 401/403)也吞成"正常空结果", 运维无法区分 LLM 崩溃 vs 正常空输出。

分类:
- DegradableError: 解析失败 / LLM 空返回 / 瞬态网络抖动 / 5xx 服务端瞬态硬错 — 引擎降级返默认 dataclass, 写 .error。
- NonDegradableError: 配置错 / 认证错 (LLM 401/403) / 模型未配置 — 不可恢复, 必须上抛让上层 (CLI ClickException / serve 502) 显式处理。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """A12: 引擎异常基类 — 所有引擎 LLM 调用相关错误的共同根。"""


class DegradableError(EngineError):
    """可降级错误 — 解析失败 / LLM 空返回 / 瞬态网络 / 5xx 服务端瞬态。引擎降级返默认 dataclass。"""


class NonDegradableError(EngineError):
    """不可降级错误 — 配置错 / 认证错 (LLM 401/403) / 模型未配置。必须上抛, 不静默降级。"""


def classify_http_status(status_code: int) -> bool:
    """A12: 判 HTTP 状态码是否不可降级。

    仅认证/授权错(401/403)不可降级 — 这是配置问题, 引擎无法自行恢复, 须上抛暴露
    让运维查 key。5xx 是 LLM 服务端瞬态硬错, 网关抖动/模型未就绪都归此类,
    引擎按既有优雅降级返默认 dataclass + 写 .error, 不上抛(否则打断 CLI/serve
    既有的容错契约)。404(模型未加载)由 ai_client 单独 _ModelNotFound 重选, 不经此分类。
    """
    if status_code in (401, 403):
        logger.error("LLM 认证/授权失败 (HTTP %d) — 不可降级, 须上抛", status_code)
        return True
    if 500 <= status_code < 600:
        logger.warning("LLM 服务端瞬态硬错 (HTTP %d) — 可降级, 引擎返默认 dataclass + .error", status_code)
        return False
    return False


def rethrow_if_fatal(exc: BaseException) -> None:
    """A11/A12: 共享 engine 调用层守门 — 在引擎 `except Exception` 内调用。

    不可降级错(NonDegradableError: 配置错/认证错, 即 LLM 401/403)必须上抛暴露,
    不被 blanket except 降级成默认 dataclass。可降级错(解析失败/LLM 空返回/5xx 瞬态)
    原样返 None, 引擎继续降级返默认 dataclass + 写 .error。

    用法 (engine 各方法 catch 块第一行):
        except Exception as e:
            logger.error(...)
            rethrow_if_fatal(e)        # 认证/配置硬错上抛, 否则继续降级
            return LessonPlan(..., error=str(e))
    """
    if isinstance(exc, NonDegradableError):
        logger.error("不可降级错误, 中止降级上抛: %s", exc)
        raise exc

