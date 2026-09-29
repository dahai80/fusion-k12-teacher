"""通用场景编译路径 — 新题型不再依赖枚举模板。

架构: S1 自然语言解析 (LLM 开放提取已知量/方程) → S2 结构化 JSON DSL
(SymPy 解方程组 + 可视化原语) → S3 物理/数学拓扑 Canvas 渲染 (前端原语)。

与模板路径 (_KNOWN_SCENARIOS) 的关系: 模板命中走精品渲染; 未命中
(scenario=unknown 或校验失败) 落入本路径, 用 SymPy 通用求解兜底,
仅当 LLM 提取失败或方程不可解时才真正降级静态推导。
"""

from __future__ import annotations

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 可视化原语白名单 — S3 前端按 kind 渲染, 不执行任何 LLM 生成代码
_VISUAL_KINDS = ("number_line", "bar_model", "flow", "grid", "timeline")

_GENERIC_PROMPT = """你是数学应用题求解器。把题目转化为「已知量 + 方程组」, 严格输出 JSON。

规则:
1. 提取所有数值已知量, 每个给短英文名 (如 speed, distance, price)。
2. 未知量命名 target (若多个未知, 用 target, x2, x3 ...)。
3. 用 SymPy 语法写方程 (Python 字符串), 只用已知量名和未知量名做符号, 乘法必须写 *。
   方程右端为 0 (如 speed*target - distance 形式移项)。
4. visual 从这几种选一个最合适的可视化: number_line(线段/行程/累计),
   bar_model(比较/占比/分组), flow(流程/分步计算), grid(阵列/搭配/枚举),
   timeline(时间推算/日程)。
5. steps: 用中文写 3 步内解题思路, 每步一句。
6. answer_unit: 答案单位 (如 "米", "秒", "元", "个")。
7. 单位协调: 已知量单位不一致时先统一成同一单位再填 value (如 cm→m)。
8. 几何变形题 (切割/拼接/削成): 先列关系恒等式 (如削去体积 = 柱体积 - 锥体积 = 柱体积*2/3),
   方程右端为 0; 分数系数直接写 /3 或 *2/3, 也可用括号式 (1 - 1/3)。
9. 判断/比较类题 (能不能/够不够/谁大): 把判据数值化 — 如三角形三边关系用
   "两边之和 - 第三边" 做方程, 结果 >0 表示能, ≤0 表示不能; 在 steps 里写明结论依据。
10. pipeline: 分步推导链 (2-5 步), 每步:
   - "eval" 是确定性算式, 只允许 数字、+ - * / ( )、params.<已知量名>、results[<步骤号>]
     引用前步结果; 乘法必须写 *; 最终步的值必须等于答案。
   - "formula" 用简洁中文/符号写法 (如 "C = π×d = 3.14×0.6 = 1.884")。
   - "result_unit" 该步结果单位。
   - "title" 一句中文步骤目标。

输出 JSON 格式:
{
  "knowns": {"speed": {"value": 20, "unit": "m/s"}, "distance": {"value": 1000, "unit": "m"}},
  "unknowns": ["target"],
  "equations": ["20*target - 1000"],
  "answer_expr": "target",
  "answer_unit": "秒",
  "visual": {"kind": "number_line", "start_label": "车头上桥", "end_label": "车尾离桥", "segments": [{"label": "车长200m"}, {"label": "桥长800m"}]},
  "steps": ["总路程=车长+桥长=1000米", "时间=路程÷速度", "1000÷20=50秒"],
  "pipeline": [
    {"step": 1, "title": "求总路程", "formula": "S = 200+800 = 1000", "eval": "params.train_length + params.bridge_length", "result_unit": "米"},
    {"step": 2, "title": "求过桥时间", "formula": "t = 1000÷20 = 50", "eval": "results[1] / params.speed", "result_unit": "秒"}
  ],
  "question_focus": "过桥时间",
  "misconception_hint": "易漏加车长"
}

题目: __PROBLEM__

只输出 JSON, 不要解释。"""


def _sanitize_pipeline(raw: Any) -> list[dict[str, Any]]:
    """pipeline 白名单过滤 — 只保留受控字段与安全 eval 串 (Gemini 方案融合)。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        try:
            step_no = int(item.get("step", 0))
        except (TypeError, ValueError):
            continue
        if step_no < 1:
            continue
        eval_str = item.get("eval")
        if not isinstance(eval_str, str) or not _eval_safe(eval_str):
            continue
        out.append({
            "step": step_no,
            "title": str(item.get("title", ""))[:60],
            "formula": str(item.get("formula", ""))[:120],
            "eval": eval_str[:200],
            "result_unit": str(item.get("result_unit", ""))[:12],
        })
    return out


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Mod, ast.Pow,
    ast.Name, ast.Attribute, ast.Subscript, ast.Index, ast.Tuple, ast.Slice,
)


def _eval_safe(expr: str) -> bool:
    """静态校验 eval 串 — 只允许算术 + params.x / results[n] 访问, 拒绝调用/属性链。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False
        if isinstance(node, ast.Attribute):
            # 只允许 params.<name> / results 形态的一层属性; 禁 dunder 防逃逸
            if not isinstance(node.value, ast.Name) or node.value.id not in ("params", "results"):
                return False
            if node.attr.startswith("_"):
                return False
        if isinstance(node, ast.Name) and node.id not in ("params", "results"):
            return False
    return True


def eval_pipeline(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """执行分步 pipeline (受限 AST 求值, 非 new Function)。

    返回 {"steps": [...带 value 的步骤...], "final": 终值}; 任一步失败返回 None。
    """
    pipeline = parsed.get("pipeline") or []
    if not pipeline:
        return None
    params = parsed["knowns"]
    results: dict[int, float] = {}
    steps_out: list[dict[str, Any]] = []
    for item in pipeline:
        try:
            tree = ast.parse(item["eval"], mode="eval")
            val = float(_ast_eval(tree.body, params, results))
        except Exception:
            return None
        if val != val or val in (float("inf"), float("-inf")):
            return None
        results[item["step"]] = val
        steps_out.append({**item, "value": val})
    if not steps_out:
        return None
    return {"steps": steps_out, "final": results[steps_out[-1]["step"]]}


def _ast_eval(node: ast.AST, params: dict[str, float], results: dict[int, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        lh, rh = _ast_eval(node.left, params, results), _ast_eval(node.right, params, results)
        if isinstance(node.op, ast.Add):
            return lh + rh
        if isinstance(node.op, ast.Sub):
            return lh - rh
        if isinstance(node.op, ast.Mult):
            return lh * rh
        if isinstance(node.op, ast.Div):
            if rh == 0:
                raise ZeroDivisionError
            return lh / rh
        if isinstance(node.op, ast.Mod):
            if rh == 0:
                raise ZeroDivisionError
            return lh % rh
        if isinstance(node.op, ast.Pow):
            return lh ** rh
    if isinstance(node, ast.UnaryOp):
        v = _ast_eval(node.operand, params, results)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "params" and node.attr in params:
            return float(params[node.attr])
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "results":
        idx = node.slice
        if isinstance(idx, ast.Constant) and isinstance(idx.value, int):
            if idx.value in results:
                return results[idx.value]
        raise KeyError("results index")
    raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


def _clean_equation(eq: str) -> str:
    """清洗 LLM 方程串 — 全角符号/中文标点/等号转 SymPy 可解析形态, 清洗后为空则丢弃。"""
    out = eq.strip()
    for a, b in (("＝", "="), ("＋", "+"), ("－", "-"), ("×", "*"), ("÷", "/"),
                 ("（", "("), ("）", ")"), ("，", ","), (":", "/"), ("：", "/")):
        out = out.replace(a, b)
    # LLM 常在方程里混入中文单位/注释 (如 "12*5 - target（立方厘米）") —
    # 变量名约定为英文标识符, 剥离中文字符通常只去掉注释, 比整条丢弃召回率高
    cleaned = "".join(ch for ch in out if not ("\u4e00" <= ch <= "\u9fff"))
    out = cleaned.strip()
    if not out:
        return ""
    # LLM 常写完整等式 "lhs = rhs" — 约定是右端为 0, 此处统一转 lhs - (rhs)
    if "=" in out:
        lhs, _, rhs = out.partition("=")
        lhs, rhs = lhs.strip(), rhs.strip()
        if not lhs:
            return ""
        if rhs and rhs != "0":
            out = f"{lhs} - ({rhs})"
        else:
            out = lhs
    return out


def _safe_sympy_solve(knowns: dict[str, float], equations: list[str],
                      unknowns: list[str], answer_expr: str) -> dict[str, Any] | None:
    """SymPy 解方程组 — 超时/异常/解非数值均返回 None (调用方降级)。"""
    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            implicit_multiplication_application,
            parse_expr,
            standard_transformations,
        )

        transformations = (*standard_transformations, implicit_multiplication_application)
        local: dict[str, Any] = {}
        for name in knowns:
            local[name] = sympy.Float(knowns[name])
        symbols = {}
        for name in unknowns:
            sym = sympy.Symbol(name, real=True)
            symbols[name] = sym
            local[name] = sym
        eqs = []
        for eq_str in equations[:6]:
            cleaned = _clean_equation(eq_str)
            if not cleaned:
                continue
            try:
                expr = parse_expr(cleaned, local_dict=local, transformations=transformations)
            except Exception as exc:
                logger.info("generic_pipeline: 方程 %r 解析失败 %s", cleaned, exc)
                continue
            eqs.append(expr)
        if not eqs:
            return None
        sols = sympy.solve(eqs, list(symbols.values()), dict=True, timeout=5.0)
        if not sols:
            return None
        sol = sols[0]
        result: dict[str, Any] = {}
        for name, sym in symbols.items():
            val = sol.get(sym)
            if val is None:
                return None
            try:
                fval = float(val)
            except (TypeError, ValueError):
                return None
            if fval != fval or fval in (float("inf"), float("-inf")):  # NaN/inf
                return None
            result[name] = fval
        # answer_expr 若是表达式 (如 speed*target), 代入求值
        if answer_expr and answer_expr in result:
            result["__answer__"] = result[answer_expr]
        elif answer_expr:
            try:
                ans_expr = parse_expr(answer_expr, local_dict={**local, **symbols},
                                      transformations=transformations)
                ans_val = ans_expr.subs(sol)
                result["__answer__"] = float(ans_val)
            except Exception:
                result["__answer__"] = result.get(unknowns[0], 0.0) if unknowns else 0.0
        else:
            result["__answer__"] = result.get(unknowns[0], 0.0) if unknowns else 0.0
        return result
    except Exception as exc:
        logger.info("generic_pipeline: sympy 求解失败 %s", exc)
        return None


def _sanitize_visual(raw: Any) -> dict[str, Any]:
    """可视化配置白名单过滤 — 只保留已知 kind 与受控字段, 防注入任意结构。"""
    if not isinstance(raw, dict):
        return {"kind": "number_line"}
    kind = str(raw.get("kind", "number_line"))
    if kind not in _VISUAL_KINDS:
        kind = "number_line"
    out: dict[str, Any] = {"kind": kind}
    for key in ("start_label", "end_label", "title", "unit"):
        val = raw.get(key)
        if isinstance(val, str):
            out[key] = val[:60]
    segs = raw.get("segments")
    if isinstance(segs, list):
        clean = []
        for s in segs[:8]:
            if isinstance(s, dict) and isinstance(s.get("label"), str):
                clean.append({"label": s["label"][:60],
                              "value": s.get("value") if isinstance(s.get("value"), (int, float)) else None})
        if clean:
            out["segments"] = clean
    return out


def build_generic_prompt(problem: str) -> str:
    # replace 而非 format — prompt 内含大量 JSON 大括号, format 转义易错
    return _GENERIC_PROMPT.replace("__PROBLEM__", problem)


def parse_generic_extraction(raw: str) -> dict[str, Any] | None:
    """解析 S1 输出并做结构校验 — 非法/缺关键字段返回 None。"""
    from ...._parse import parse_json
    data = parse_json(raw)
    if not isinstance(data, dict):
        return None
    knowns_raw = data.get("knowns")
    if not isinstance(knowns_raw, dict) or not knowns_raw:
        return None
    knowns: dict[str, float] = {}
    units: dict[str, str] = {}
    for name, item in list(knowns_raw.items())[:12]:
        if not isinstance(name, str) or not name.isidentifier():
            continue
        if isinstance(item, dict):
            try:
                knowns[name] = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            units[name] = str(item.get("unit", ""))[:12]
        else:
            try:
                knowns[name] = float(item)
            except (TypeError, ValueError):
                continue
    if not knowns:
        return None
    unknowns = [u for u in data.get("unknowns", []) if isinstance(u, str) and u.isidentifier()][:4]
    if not unknowns:
        unknowns = ["target"]
    equations = [e for e in data.get("equations", []) if isinstance(e, str) and 0 < len(e) < 300][:6]
    if not equations:
        return None
    return {
        "knowns": knowns,
        "units": units,
        "unknowns": unknowns,
        "equations": equations,
        "answer_expr": str(data.get("answer_expr", unknowns[0]))[:60],
        "answer_unit": str(data.get("answer_unit", ""))[:12],
        "visual": _sanitize_visual(data.get("visual")),
        "steps": [str(s)[:120] for s in data.get("steps", [])[:5] if isinstance(s, str)],
        "pipeline": _sanitize_pipeline(data.get("pipeline")),
        "question_focus": str(data.get("question_focus", ""))[:60],
        "misconception_hint": str(data.get("misconception_hint", ""))[:120],
    }


def solve_generic(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """S2: SymPy 解方程组, 返回 {unknown: value, __answer__: value} 或 None。"""
    return _safe_sympy_solve(parsed["knowns"], parsed["equations"],
                             parsed["unknowns"], parsed["answer_expr"])
