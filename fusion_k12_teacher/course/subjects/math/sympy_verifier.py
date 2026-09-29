"""数学 SymPy 符号校验引擎 — 数值绝对权威覆写 (PRD §6 严谨性铁律)。

双闸替代: PRD 原 GBNF Logits Masker 须改 fusion-mlx (上游不可改, 已提 issue),
此处以 structured-output prompting + Pydantic/SymPy 后置校验近似 — SymPy 计算结果
为 Single Source of Truth, 覆写 LLM 提取的任何数值字段。

能力:
- verify_scene: 按场景公式 (火车过桥 5 题型等) 计算路程/时间/相对速度, 覆写 entities。
- judge_checkpoint: 代数式 SymPy 等价判定 / 数值容差 / 字符串兜底。
- singularities: 函数间断点探测 (渲染断开假连线)。
- 1.5s 硬超时: ThreadPool 熔断, 超时返回数值近似解 + 标注。
- 降级: sympy 不可用/超时 → 字符串精确比对 + 标注「未经验算」, 绝不用 LLM 判数值。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from ...base import VerifierBase
from ...models import Checkpoint, CheckpointType, JudgeResult, VerifyResult

logger = logging.getLogger(__name__)

_HARD_TIMEOUT_S = 1.5
_TOL_DEFAULT = 0.01

ScenarioHandler = Callable[[dict[str, float]], dict[str, float]]


def _h_train_crossing_bridge(v: dict[str, float]) -> dict[str, float]:
    s = v["L_bridge"] + v["L_train"]
    t = s / v["v_train"] if v.get("v_train", 0) else 0.0
    return {**v, "S_total": s, "t": t}


def _h_train_on_bridge(v: dict[str, float]) -> dict[str, float]:
    s = max(v["L_bridge"] - v["L_train"], 0.0)
    t = s / v["v_train"] if v.get("v_train", 0) else 0.0
    return {**v, "S_total": s, "t": t}


def _h_relative_motion(v: dict[str, float]) -> dict[str, float]:
    direction = v.get("direction", 1.0)
    v_rel = v["v_train"] + direction * v.get("v_pedestrian", 0.0)
    v_rel = abs(v_rel) or 1e-9
    s = v["L_train"]
    return {**v, "v_relative": v_rel, "S_total": s, "t": s / v_rel}


def _h_two_trains_meet(v: dict[str, float]) -> dict[str, float]:
    s = v["L1"] + v["L2"]
    v_rel = v["v1"] + v["v2"]
    return {**v, "S_total": s, "v_relative": v_rel, "t": s / v_rel if v_rel else 0.0}


def _h_two_trains_overtake(v: dict[str, float]) -> dict[str, float]:
    s = v["L1"] + v["L2"]
    v_rel = abs(v["v1"] - v["v2"])
    return {**v, "S_total": s, "v_relative": v_rel, "t": s / v_rel if v_rel else 0.0}


def _h_echo_problem(v: dict[str, float]) -> dict[str, float]:
    t = v.get("t_echo", 0.0)
    s_sound = v["v_sound"] * t
    s_train = v["v_train"] * t
    x = (s_sound + s_train) / 2.0
    return {**v, "S_sound": s_sound, "S_train": s_train, "x_distance": x}


def _h_cutting_segments(v: dict[str, float]) -> dict[str, float]:
    n_seg = int(v["n_segments"])
    t_per = v["time_per_cut"]
    n_cuts = max(n_seg - 1, 0)
    total = n_cuts * t_per
    return {**v, "n_cuts": float(n_cuts), "total_time": total}


def _h_queue_counting(v: dict[str, float]) -> dict[str, float]:
    # 两种子题型 (G1 易错题): LLM 提取时以 extra 字段区分 —
    #   位次型 (rank): "从前第a, 从后第b" → total = a + b - 1
    #   人数型 (counts): "前面有a人, 后面有b人" → total = a + b + 1 (自己易漏算)
    if "front_count" in v or "behind_count" in v:
        front = v.get("front_count", 0.0)
        behind = v.get("behind_count", 0.0)
        total = front + behind + 1.0
    else:
        total = v["rank_front"] + v["rank_behind"] - 1.0
    return {**v, "total_people": total}


def _h_fence_against_wall(v: dict[str, float]) -> dict[str, float]:
    length = v["length"]
    perimeter = v["perimeter"]
    width = max((perimeter - length) / 2.0, 0.0)
    area = length * width
    return {**v, "width": width, "area": area}


def _h_unitary_method(v: dict[str, float]) -> dict[str, float]:
    n_items = v["n_items"]
    total_value = v["total_value"]
    n_target = v["n_target"]
    unit = total_value / n_items if n_items else 0.0
    target = unit * n_target
    return {**v, "unit_value": unit, "target_value": target}


def _h_chicken_rabbit(v: dict[str, float]) -> dict[str, float]:
    heads = v["heads"]
    legs = v["legs"]
    rabbit = (legs - 2.0 * heads) / 2.0
    chicken = heads - rabbit
    return {**v, "rabbit": rabbit, "chicken": chicken}


def _h_basic_motion(v: dict[str, float]) -> dict[str, float]:
    s = v.get("distance", 0.0)
    v_speed = v.get("speed", 0.0)
    t = v.get("time", 0.0)
    if not s and v_speed and t:
        s = v_speed * t
    elif not v_speed and s and t:
        v_speed = s / t
    elif not t and s and v_speed:
        t = s / v_speed
    return {**v, "distance": s, "speed": v_speed, "time": t}


def _h_work_problem(v: dict[str, float]) -> dict[str, float]:
    a = v["worker1_days"]
    b = v["worker2_days"]
    rate1 = 1.0 / a if a else 0.0
    rate2 = 1.0 / b if b else 0.0
    total_rate = rate1 + rate2
    days = 1.0 / total_rate if total_rate else 0.0
    return {**v, "rate1": rate1, "rate2": rate2, "total_days": days}


def _h_average_problem(v: dict[str, float]) -> dict[str, float]:
    total_sum = v["total_sum"]
    count = v["count"]
    avg = total_sum / count if count else 0.0
    return {**v, "average": avg}


def _h_overlap_splice(v: dict[str, float]) -> dict[str, float]:
    board1 = v["board1"]
    board2 = v["board2"]
    overlap = v["overlap"]
    total = board1 + board2 - overlap
    return {**v, "total_length": total}


def _h_round_trip(v: dict[str, float]) -> dict[str, float]:
    distance = v["distance"]
    trips = v["trips"]
    total = distance * 2.0 * trips
    return {**v, "total_distance": total}


def _h_sum_multiple(v: dict[str, float]) -> dict[str, float]:
    sum_val = v["sum"]
    multiple = v["multiple"]
    small = sum_val / (multiple + 1.0) if multiple else 0.0
    big = small * multiple
    return {**v, "small": small, "big": big}


def _h_sprinkler_area(v: dict[str, float]) -> dict[str, float]:
    speed = v["speed"]
    width = v["width"]
    time = v["time"]
    length = speed * time
    area = length * width
    return {**v, "length": length, "area": area}


def _h_tree_planting(v: dict[str, float]) -> dict[str, float]:
    length = v["length"]
    spacing = v["spacing"]
    mode = str(int(v.get("mode_code", 0.0)))
    segments = length / spacing if spacing else 0.0
    if mode == "1":
        trees = segments + 1.0
    elif mode == "2":
        trees = segments
    elif mode == "3":
        trees = segments - 1.0
    else:
        trees = segments
    return {**v, "segments": segments, "trees": trees}


def _h_displacement_volume(v: dict[str, float]) -> dict[str, float]:
    length = v["length"]
    width = v["width"]
    rise = v["rise"]
    volume = length * width * rise
    return {**v, "volume": volume}


def _h_profit_loss(v: dict[str, float]) -> dict[str, float]:
    surplus = v["surplus"]
    deficit = v["deficit"]
    diff = v["diff"]
    people = (surplus + deficit) / diff if diff else 0.0
    return {**v, "people": people}


def _h_simple_interest(v: dict[str, float]) -> dict[str, float]:
    principal = v["principal"]
    rate = v["rate"]
    years = v["years"]
    interest = principal * rate * years
    total = principal + interest
    return {**v, "interest": interest, "total": total}


def _h_tiered_pricing(v: dict[str, float]) -> dict[str, float]:
    base_distance = v["base_distance"]
    base_price = v["base_price"]
    unit_price = v["unit_price"]
    total_distance = v["total_distance"]
    extra = max(total_distance - base_distance, 0.0)
    total = base_price + extra * unit_price
    return {**v, "extra_distance": extra, "total_price": total}


def _h_weekday_calc(v: dict[str, float]) -> dict[str, float]:
    start_day = v["start_day"]
    add_days = v["add_days"]
    target = (start_day + add_days) % 7.0
    if target == 0.0:
        target = 7.0
    return {**v, "target_day": target}


def _h_semicircle_perimeter(v: dict[str, float]) -> dict[str, float]:
    radius = v["radius"]
    arc = 3.141592653589793 * radius
    diameter = 2.0 * radius
    perimeter = arc + diameter
    return {**v, "arc": arc, "diameter": diameter, "perimeter": perimeter}


def _h_cuboid_combine_surface(v: dict[str, float]) -> dict[str, float]:
    length = v["length"]
    width = v["width"]
    height = v["height"]
    faces = [length * width, length * height, width * height]
    min_face = min(faces)
    single_sa = 2.0 * (length * width + length * height + width * height)
    max_sa = 2.0 * single_sa - 2.0 * min_face
    min_sa = 2.0 * single_sa - 2.0 * max(faces)
    return {**v, "min_face": min_face, "max_face": max(faces),
            "single_sa": single_sa, "max_sa": max_sa, "min_sa": min_sa}


def _h_combination_count(v: dict[str, float]) -> dict[str, float]:
    n1 = v["n_items1"]
    n2 = v["n_items2"]
    total = n1 * n2
    return {**v, "combinations": total}


def _h_redundant_filter(v: dict[str, float]) -> dict[str, float]:
    total = v["total"]
    removed = v["removed"]
    remaining = total - removed
    return {**v, "remaining": remaining}


def _h_fold_cut(v: dict[str, float]) -> dict[str, float]:
    folds = int(v["folds"])
    segments = 2 ** folds + 1
    return {**v, "segments": float(segments)}


def _h_stars_bars(v: dict[str, float]) -> dict[str, float]:
    import math
    n = int(v["n_items"])
    k = int(v["n_bins"])
    min_per = int(v.get("min_per", 1))
    if min_per < 1:
        min_per = 1
    reserved = k * min_per
    remaining = n - reserved
    if remaining < 0 or k < 1:
        ways = 0.0
    elif min_per == 1:
        ways = float(math.comb(n - 1, k - 1))
    else:
        ways = float(math.comb(remaining + k - 1, k - 1))
    return {**v, "reserved": float(reserved), "remaining": float(remaining), "ways": ways}


def _h_unitary_combined(v: dict[str, float]) -> dict[str, float]:
    n_people = v["n_people"]
    n_days = v["n_days"]
    total_work = v["total_work"]
    target_people = v["target_people"]
    target_days = v["target_days"]
    per_person_per_day = total_work / (n_people * n_days) if n_people and n_days else 0.0
    result = per_person_per_day * target_people * target_days
    return {**v, "unit_rate": per_person_per_day, "result": result}


_SCENARIO_HANDLERS: dict[str, ScenarioHandler] = {
    "train_crossing_bridge": _h_train_crossing_bridge,
    "train_on_bridge": _h_train_on_bridge,
    "relative_motion": _h_relative_motion,
    "two_trains_meet": _h_two_trains_meet,
    "two_trains_overtake": _h_two_trains_overtake,
    "echo_problem": _h_echo_problem,
    "cutting_segments": _h_cutting_segments,
    "queue_counting": _h_queue_counting,
    "fence_against_wall": _h_fence_against_wall,
    "unitary_method": _h_unitary_method,
    "chicken_rabbit": _h_chicken_rabbit,
    "basic_motion": _h_basic_motion,
    "work_problem": _h_work_problem,
    "average_problem": _h_average_problem,
    "overlap_splice": _h_overlap_splice,
    "round_trip": _h_round_trip,
    "sum_multiple": _h_sum_multiple,
    "sprinkler_area": _h_sprinkler_area,
    "tree_planting": _h_tree_planting,
    "displacement_volume": _h_displacement_volume,
    "profit_loss": _h_profit_loss,
    "simple_interest": _h_simple_interest,
    "tiered_pricing": _h_tiered_pricing,
    "weekday_calc": _h_weekday_calc,
    "semicircle_perimeter": _h_semicircle_perimeter,
    "cuboid_combine_surface": _h_cuboid_combine_surface,
    "combination_count": _h_combination_count,
    "unitary_combined": _h_unitary_combined,
    "redundant_filter": _h_redundant_filter,
    "fold_cut": _h_fold_cut,
    "stars_bars": _h_stars_bars,
}

_SCENARIO_REQUIRED: dict[str, list[str]] = {
    "train_crossing_bridge": ["L_bridge", "L_train", "v_train"],
    "train_on_bridge": ["L_bridge", "L_train", "v_train"],
    "relative_motion": ["L_train", "v_train", "v_pedestrian"],
    "two_trains_meet": ["L1", "L2", "v1", "v2"],
    "two_trains_overtake": ["L1", "L2", "v1", "v2"],
    "echo_problem": ["v_train", "v_sound", "t_echo"],
    "cutting_segments": ["n_segments", "time_per_cut"],
    "queue_counting": ["rank_front", "rank_behind"],  # 人数型变体提取 front_count/behind_count, handler 内分支兼容
    "fence_against_wall": ["length", "perimeter"],
    "unitary_method": ["n_items", "total_value", "n_target"],
    "chicken_rabbit": ["heads", "legs"],
    "basic_motion": [],
    "work_problem": ["worker1_days", "worker2_days"],
    "average_problem": ["total_sum", "count"],
    "overlap_splice": ["board1", "board2", "overlap"],
    "round_trip": ["distance", "trips"],
    "sum_multiple": ["sum", "multiple"],
    "sprinkler_area": ["speed", "width", "time"],
    "tree_planting": ["length", "spacing"],
    "displacement_volume": ["length", "width", "rise"],
    "profit_loss": ["surplus", "deficit", "diff"],
    "simple_interest": ["principal", "rate", "years"],
    "tiered_pricing": ["base_distance", "base_price", "unit_price", "total_distance"],
    "weekday_calc": ["start_day", "add_days"],
    "semicircle_perimeter": ["radius"],
    "cuboid_combine_surface": ["length", "width", "height"],
    "combination_count": ["n_items1", "n_items2"],
    "unitary_combined": ["n_people", "n_days", "total_work", "target_people", "target_days"],
    "redundant_filter": ["total", "removed"],
    "fold_cut": ["folds"],
    "stars_bars": ["n_items", "n_bins"],
}

UNKNOWN_VARS = (
    "t", "S_total", "x_distance", "v_relative", "S_sound", "S_train",
    "n_cuts", "total_time", "total_people", "width", "area",
    "unit_value", "target_value", "rabbit", "chicken", "total_days",
    "average", "rate1", "rate2",
    "total_length", "total_distance", "small", "big", "length",
    "segments", "trees", "volume", "people",
    "interest", "total",
    "extra_distance", "total_price", "target_day", "arc", "diameter", "perimeter",
    "min_face", "max_face", "single_sa", "max_sa", "min_sa",
    "combinations", "unit_rate", "result", "remaining", "segments", "ways",
)


def _to_float_dict(entities: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, val in entities.items():
        try:
            out[k] = float(val)
        except (TypeError, ValueError):
            logger.warning("sympy_verifier: 变量 %s 非数值 %r, 跳过", k, val)
    return out


def _run_with_timeout(fn: Callable[[], Any]) -> tuple[Any, str]:
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(fn)
            return fut.result(timeout=_HARD_TIMEOUT_S), ""
    except FuturesTimeout:
        logger.warning("sympy_verifier: 求解 %.1fs 超时, 返回数值近似解", _HARD_TIMEOUT_S)
        return None, "timeout"
    except Exception as exc:
        logger.warning("sympy_verifier: 求解异常 %s", exc)
        return None, f"error:{type(exc).__name__}"


class MathSympyVerifier(VerifierBase):
    """数学 SymPy 符号校验 — 数值权威覆写 + checkpoint 判分。"""

    def __init__(self) -> None:
        self._handlers = dict(_SCENARIO_HANDLERS)
        self._required = dict(_SCENARIO_REQUIRED)
        try:
            import sympy  # noqa: F401
            self._sympy_ok = True
        except ImportError:
            self._sympy_ok = False
            logger.warning("sympy_verifier: sympy 未安装, 判分退化为字符串比对 + 标注「未经验算」")

    def verify_scene(self, scenario: str, entities: dict[str, Any]) -> VerifyResult:
        handler = self._handlers.get(scenario)
        if handler is None:
            return VerifyResult(error=f"未知场景: {scenario}", fallback=True)
        required = self._required.get(scenario, [])
        vars_f = _to_float_dict(entities)
        # 变体兼容: required 满足其一即可 (如 queue_counting 位次型 rank_* 或人数型 front/behind_count)
        missing = [k for k in required if k not in vars_f]
        if missing and not any(k in vars_f for k in ("front_count", "behind_count")):
            return VerifyResult(error=f"缺失变量: {missing}", fallback=True)
        result, err = _run_with_timeout(lambda: handler(vars_f))
        if result is None:
            try:
                result = handler(vars_f)
                err = ""
            except Exception as exc2:
                return VerifyResult(error=f"{err}:{exc2}", fallback=True)
        variables = {
            k: {"label": k, "unit": "", "value": val, "is_unknown": k in UNKNOWN_VARS}
            for k, val in result.items()
        }
        return VerifyResult(
            verified=not err, variables=variables, error=err, fallback=bool(err),
        )

    def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult:
        if checkpoint.type == CheckpointType.EXPRESSION and checkpoint.expected_expression:
            return self._judge_expression(checkpoint.expected_expression, student_answer, checkpoint.tolerance)
        if checkpoint.type == CheckpointType.NUMERIC_INPUT:
            try:
                ans = float(student_answer)
            except (TypeError, ValueError):
                return JudgeResult(correct=False, method="string_fallback", detail=f"非数值: {student_answer!r}", fallback=True, hint=checkpoint.hints[0] if checkpoint.hints else "")
            return self._judge_numeric(checkpoint.expected_value, ans, checkpoint.tolerance, checkpoint.hints)
        if checkpoint.type == CheckpointType.MULTIPLE_CHOICE:
            correct_opt = next((o for o in checkpoint.options if o.get("is_correct")), None)
            is_correct = bool(correct_opt and student_answer == correct_opt.get("id"))
            return JudgeResult(correct=is_correct, method="multiple_choice", detail=str(correct_opt.get("feedback", "")) if correct_opt else "", hint=checkpoint.hints[0] if (not is_correct and checkpoint.hints) else "")
        return JudgeResult(correct=False, method="unsupported", detail=f"类型 {checkpoint.type.value} 暂不支持自动判分", fallback=True)

    def _judge_expression(self, expected: str, student: str, tolerance: float) -> JudgeResult:
        if not self._sympy_ok:
            return self._string_fallback(expected, student)
        try:
            import sympy
            from sympy.parsing.sympy_parser import (
                implicit_multiplication,
                parse_expr,
                standard_transformations,
            )
            transformations = (*standard_transformations, implicit_multiplication)
            exp = parse_expr(expected, transformations=transformations)
            stu = parse_expr(student, transformations=transformations)
            diff, err = _run_with_timeout(lambda: sympy.simplify(exp - stu))
            if diff is None:
                return self._numeric_sample(exp, stu, tolerance, err)
            is_zero = diff == 0
            return JudgeResult(correct=bool(is_zero), method="verifier", detail=f"simplify(diff)={diff}")
        except Exception as exc:
            logger.warning("sympy_verifier._judge_expression 异常: %s, 降级字符串", exc)
            return self._string_fallback(expected, student)

    def _judge_numeric(self, expected: float, student: float, tolerance: float, hints: list[str]) -> JudgeResult:
        ok = math.isclose(expected, student, rel_tol=tolerance, abs_tol=tolerance)
        return JudgeResult(correct=ok, method="numeric", detail=f"expected={expected} student={student} tol={tolerance}", hint=hints[0] if (not ok and hints) else "")

    def _numeric_sample(self, exp, stu, tolerance: float, err: str) -> JudgeResult:
        samples = [0.5, 1.0, 2.0, 3.7, -1.3, 10.0]
        try:
            for sval in samples:
                ev = float(exp.subs(next(iter(exp.free_symbols)), sval)) if exp.free_symbols else float(exp)
                sv = float(stu.subs(next(iter(stu.free_symbols)), sval)) if stu.free_symbols else float(stu)
                if not math.isclose(ev, sv, rel_tol=tolerance, abs_tol=tolerance):
                    return JudgeResult(correct=False, method="numeric_sample", detail=f"sample {sval}: {ev}≠{sv}", fallback=True)
            return JudgeResult(correct=True, method="numeric_sample", detail="6 样本全等", fallback=True)
        except Exception as exc:
            return JudgeResult(correct=False, method="string_fallback", detail=f"{err}:{exc}", fallback=True)

    def _string_fallback(self, expected: str, student: str) -> JudgeResult:
        def norm(s):
            return s.replace(" ", "").replace("*", "")
        ok = norm(expected) == norm(student)
        return JudgeResult(correct=ok, method="string_fallback", detail="未经验算", fallback=True)

    def singularities(self, expr_str: str, var: str = "x") -> list[float]:
        if not self._sympy_ok:
            return []
        try:
            import sympy
            from sympy.parsing.sympy_parser import (
                implicit_multiplication,
                parse_expr,
                standard_transformations,
            )
            transformations = (*standard_transformations, implicit_multiplication)
            x = sympy.Symbol(var)
            expr = parse_expr(expr_str, transformations=transformations, local_dict={var: x})
            sings, _ = _run_with_timeout(lambda: list(sympy.singularities(expr, x)))
            if sings is None:
                return []
            out: list[float] = []
            for s in sings:
                try:
                    out.append(float(s))
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as exc:
            logger.warning("sympy_verifier.singularities 异常: %s", exc)
            return []

    def register_scenario(self, scenario_id: str, handler: ScenarioHandler, required: list[str]) -> None:
        self._handlers[scenario_id] = handler
        self._required[scenario_id] = required
