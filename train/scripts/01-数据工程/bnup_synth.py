#!/usr/bin/env python
"""BNUP SFT 语料程序化合成器 (sft-dpo-1013 §2.2)。

核心设计 (直击 E1 参数名漂移):
- 变量表 SSoT: question/thinking/parameters/pipeline.eval 全部从同一 vars dict
  渲染 — eval 引用键名与 parameters 定义 by construction 一致。
- 逆构采样: 先采样中间量 (如 v,t), 反推题面量 (L_bridge=v*t-L_train),
  保证 ground_truth 整洁且 eval 可精确复算。
- 四道闸 (任一失败即丢弃并计数, 目标 0):
    gate1 JSON roundtrip
    gate2 jsonschema (eval_harness.DSL_SCHEMA — 与生产 5 步瀑布同源)
    gate3 eval 引用键名 == parameters 键 (双向) + results[n] 只引用已有步 + ASCII 运算符
    gate4 生产求值器 (BNUPEvaluator.evaluate_eval_expression) 复算 == 独立算术 expect (ε=0.01)
- thinking 四段固定结构, 第 3 段显式示范 "键名核对" (E1 行为级纠正)。

用法:
  python scripts/bnup_synth.py --total 4000 --holdout 200 --seed 2026 \
      --out data/bnup/raw_sft_v1.json
输出 raw JSON 数组 [{question, thinking, dsl, template_id, category, split, ...}]
— `ft bnup-prep --sft` 的直接输入。
"""
from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable
from pathlib import Path

import jsonschema

from fusion_k12_teacher.eval.eval_harness import DSL_SCHEMA, BNUPEvaluator

PARAM_RE = __import__("re").compile(r"params\.(\w+)")
RESULT_RE = __import__("re").compile(r"results\[(\d+)\]")
_EVAL = BNUPEvaluator()
PI = 3.14


# ────────────────────────── 工具 ──────────────────────────

def V(label: str, value: float, unit: str) -> dict:
    return {"label": label, "value": float(value), "unit": unit}


# v3 schema 限定 fallback_type ∈ {tape_diagram, flow_card} — 按 visual_type 映射
def fallback_for(visual: str) -> str:
    return "flow_card" if visual != "flow_card" else "tape_diagram"


def E(eid: str, etype: str, label: str) -> dict:
    # properties: {} — fusion-core SOCRATIC_DSL_V3_SCHEMA 必填 (bnup_prep 训练闸),
    # k12 eval_harness 宽松 schema 对额外字段无限制 (训练/生产同源合规)
    return {"id": eid, "type": etype, "label": label, "properties": {}}


def fmt_num(v: float) -> str:
    v = round(float(v), 6)
    return str(int(v)) if v == int(v) else f"{v:g}"


def ri(rng: random.Random, a: int, b: int) -> int:
    return rng.randint(a, b)


def pick(rng: random.Random, seq):
    return rng.choice(seq)


def build_pipeline(ents: list[dict], steps) -> list[dict]:
    """steps: [(title, formula, eval_expr, result_unit)] → pipeline 段 (均匀 progress)。"""
    n = len(steps)
    ent_ids = [e["id"] for e in ents]
    pipe = []
    for i, (title, formula, expr, unit) in enumerate(steps, 1):
        lo = round((i - 1) / n, 3)
        hi = 1.0 if i == n else round(i / n, 3)
        pipe.append({
            "step": i, "title": title, "formula": formula, "eval": expr,
            "result_unit": unit,
            "visual_state": {"progress_range": [lo, hi],
                             "active_entities": ent_ids,
                             "action": "result" if i == n else "compute"},
        })
    return pipe


def param_refs(steps) -> set[str]:
    refs: set[str] = set()
    for _, _, expr, _ in steps:
        refs |= set(PARAM_RE.findall(expr))
    return refs


def _all_step_vals(pipe, vars_d) -> dict[int, float]:
    """逐前缀求值 (与生产 evaluate_eval_expression 同语义), 返回 {step: value}。"""
    out: dict[int, float] = {}
    for k in range(1, len(pipe) + 1):
        out[k] = float(_EVAL.evaluate_eval_expression(pipe[:k], vars_d))
    return out


def display_eval(expr: str, vars_d: dict, step_vals: dict[int, float]) -> str:
    out = PARAM_RE.sub(lambda m: fmt_num(vars_d[m.group(1)]["value"]), expr)
    return RESULT_RE.sub(lambda m: fmt_num(step_vals[int(m.group(1))]), out)


def build_thinking(topic: str, vars_d: dict, steps, step_vals: dict[int, float]) -> str:
    """四段固定结构 — 第 3 段显式键名核对 (E1 行为级示范)。"""
    p1 = "; ".join(f"{fmt_num(d['value'])}{d['unit']}({d['label']}→{name})"
                   for name, d in vars_d.items())
    p2 = "; ".join(f"{t}: {f}" for t, f, _, _ in steps)
    refs = sorted(param_refs(steps))
    p3 = (f"核对键名: eval 引用 {{ {', '.join(refs)} }} — "
          f"与 parameters 键名逐字一致(区分大小写) ✓")
    p4 = "; ".join(f"{t}: {display_eval(e, vars_d, step_vals)}"
                   f"={fmt_num(step_vals[i])}{u}"
                   for i, (t, _, e, u) in enumerate(steps, 1))
    return (f"【{topic}】\n1. 提取参数: {p1}\n2. 解题步骤: {p2}\n"
            f"3. {p3}\n4. 验算: {p4}")


def check_gates(dsl: dict, vars_d: dict, steps, expect: float,
                allow_unused: bool) -> tuple[dict[int, float] | None, str]:
    """四道闸。返回 (step_vals, "") 或 (None, 原因)。"""
    # gate1 JSON roundtrip
    s = json.dumps(dsl, ensure_ascii=False)
    if json.loads(s) != dsl:
        return None, "gate1 json roundtrip"
    # gate2 jsonschema (生产同源)
    try:
        jsonschema.Draft202012Validator(DSL_SCHEMA).validate(dsl)
    except jsonschema.ValidationError as e:
        return None, f"gate2 schema: {e.message[:80]}"
    # gate3 引用一致性
    keys = set(vars_d.keys())
    refs = param_refs(steps)
    if not refs <= keys:
        return None, f"gate3 eval 未定义引用: {sorted(refs - keys)}"
    if not allow_unused and refs != keys:
        return None, f"gate3 参数未全部引用: 定义{sorted(keys)} vs 引用{sorted(refs)}"
    n = len(steps)
    for i, (_, _, expr, _) in enumerate(steps, 1):
        for r in RESULT_RE.findall(expr):
            if not (1 <= int(r) < i):
                return None, f"gate3 step{i} 非法 results[{r}]"
        if any(ch in expr for ch in ("×", "÷", "−")):
            return None, f"gate3 非 ASCII 运算符: {expr}"
    # gate4 生产求值器复算 == 独立算术 expect
    pipe = dsl["pipeline"]
    step_vals = _all_step_vals(pipe, vars_d)
    final = step_vals[n]
    if abs(final - float(expect)) > 0.01:
        return None, f"gate4 复算 {final} != expect {expect}"
    return step_vals, ""


# ────────────────────────── 模板注册表 ──────────────────────────
# 每个 spec: {id, grade, topic, visual, fallback,
#             gen(rng)->(vars_d, expect, extra),
#             ents(vars, extra)->list, steps(vars, extra)->list,
#             question(vars, extra, rng)->str, allow_unused?}
# vars_d: {name: {"label","value","unit"}} — SSoT

SPEC: list[dict] = []


def spec(**kw):
    kw.setdefault("allow_unused", False)

    def deco(fn: Callable) -> dict:
        kw["gen"] = fn
        SPEC.append(kw)
        return kw  # 模板名后续以 _tN["steps"]=... 方式补注册 — 返回 dict

    return deco


# ── 行程/火车家族 (track_timeline) ──

@spec(id="train_crossing_bridge", grade=5, topic="火车过桥",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("train", "moving_object", "火车")])
def _t1(rng):
    v_, t = float(ri(rng, 6, 30)), float(ri(rng, 10, 120))
    S = v_ * t
    ltr = float(ri(rng, 8, max(9, int(min(300, S // 6)))))
    v = {"L_bridge": V("桥长", S - ltr, "m"), "L_train": V("车长", ltr, "m"),
         "v_train": V("速度", v_, "m/s")}
    return v, t, None


_t1["steps"] = lambda v, x: [
    ("总路程", "L_bridge+L_train", "params.L_bridge+params.L_train", "m"),
    ("通过时间", "results[1]/v_train", "results[1]/params.v_train", "s")]
_t1["question"] = lambda v, x, rng: pick(rng, [
    f"一列长{fmt_num(v['L_train']['value'])}米的火车以{fmt_num(v['v_train']['value'])}米每秒的速度通过{fmt_num(v['L_bridge']['value'])}米的大桥，求通过时间。",
    f"一列{fmt_num(v['L_train']['value'])}米长的列车以每秒{fmt_num(v['v_train']['value'])}米的速度匀速通过{fmt_num(v['L_bridge']['value'])}米的铁路桥，从车头上桥到车尾离开共需多少秒？"])


@spec(id="train_on_bridge", grade=5, topic="火车过桥",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("train", "moving_object", "火车")])
def _t2(rng):
    v_, t = float(ri(rng, 6, 30)), float(ri(rng, 8, 90))
    S = v_ * t
    ltr = float(ri(rng, 8, max(9, int(min(300, S // 6)))))
    v = {"L_bridge": V("桥长", S + ltr, "m"), "L_train": V("车长", ltr, "m"),
         "v_train": V("速度", v_, "m/s")}
    return v, t, None


_t2["steps"] = lambda v, x: [
    ("桥上行驶路程", "L_bridge-L_train", "params.L_bridge-params.L_train", "m"),
    ("完全在桥上的时间", "results[1]/v_train", "results[1]/params.v_train", "s")]
_t2["question"] = lambda v, x, rng: f"一列长{fmt_num(v['L_train']['value'])}米的火车以{fmt_num(v['v_train']['value'])}米每秒的速度通过{fmt_num(v['L_bridge']['value'])}米的大桥，求火车完全在桥上的时间。"


@spec(id="relative_motion", grade=5, topic="行程问题",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("train", "moving_object", "火车"),
                         E("person", "object", "行人")])
def _t3(rng):
    same = rng.random() < 0.5
    v_tr, vp = float(ri(rng, 10, 30)), float(ri(rng, 1, 5))
    vr = v_tr - vp if same else v_tr + vp
    t = float(ri(rng, 5, 60))
    v = {"L_train": V("车长", vr * t, "m"), "v_train": V("火车速度", v_tr, "m/s"),
         "v_pedestrian": V("行人速度", vp, "m/s")}
    return v, t, {"dir": "同向" if same else "相向"}


_t3["steps"] = lambda v, x: [
    ("相对速度", "v_train-v_pedestrian" if x["dir"] == "同向" else "v_train+v_pedestrian",
     "params.v_train-params.v_pedestrian" if x["dir"] == "同向"
     else "params.v_train+params.v_pedestrian", "m/s"),
    ("通过时间", "L_train/results[1]", "params.L_train/results[1]", "s")]
_t3["question"] = lambda v, x, rng: (
    f"一列长{fmt_num(v['L_train']['value'])}米的火车以{fmt_num(v['v_train']['value'])}米每秒的速度行驶，"
    f"{'遇到以' if x['dir'] == '同向' else '与迎面走来的'}{fmt_num(v['v_pedestrian']['value'])}米每秒"
    f"{'同向行走的' if x['dir'] == '同向' else ''}行人，求火车{'通过' if x['dir'] == '同向' else '经过'}行人{'的时间' if x['dir'] == '同向' else '所需要的时间'}。")


@spec(id="two_trains_meet", grade=6, topic="两车错车",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("train1", "moving_object", "甲车"),
                         E("train2", "moving_object", "乙车")])
def _t4(rng):
    v1, v2 = float(ri(rng, 15, 40)), float(ri(rng, 10, 35))
    t = float(ri(rng, 5, 40))
    S = (v1 + v2) * t
    l1 = float(ri(rng, 80, int(S - 80)))
    v = {"L1": V("甲车长", l1, "m"), "L2": V("乙车长", S - l1, "m"),
         "v1": V("甲车速度", v1, "m/s"), "v2": V("乙车速度", v2, "m/s")}
    return v, t, None


_t4["steps"] = lambda v, x: [
    ("两车长度和", "L1+L2", "params.L1+params.L2", "m"),
    ("相对速度", "v1+v2", "params.v1+params.v2", "m/s"),
    ("错车时间", "results[1]/results[2]", "results[1]/results[2]", "s")]
_t4["question"] = lambda v, x, rng: (
    f"甲列车长{fmt_num(v['L1']['value'])}米以{fmt_num(v['v1']['value'])}米每秒行驶，"
    f"乙列车长{fmt_num(v['L2']['value'])}米以{fmt_num(v['v2']['value'])}米每秒行驶，两车相向而行，求错车时间。")


@spec(id="two_trains_overtake", grade=6, topic="两车超车",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("train1", "moving_object", "甲车"),
                         E("train2", "moving_object", "乙车")])
def _t5(rng):
    v2, dv = float(ri(rng, 10, 25)), float(ri(rng, 3, 20))
    v1 = v2 + dv
    t = float(ri(rng, 200 // int(dv) + 1, 200 // int(dv) + 60))
    S = dv * t
    l1 = float(ri(rng, 80, int(S - 80)))
    v = {"L1": V("甲车长", l1, "m"), "L2": V("乙车长", S - l1, "m"),
         "v1": V("甲车速度", v1, "m/s"), "v2": V("乙车速度", v2, "m/s")}
    return v, t, None


_t5["steps"] = lambda v, x: [
    ("两车长度和", "L1+L2", "params.L1+params.L2", "m"),
    ("相对速度", "v1-v2", "params.v1-params.v2", "m/s"),
    ("超车时间", "results[1]/results[2]", "results[1]/results[2]", "s")]
_t5["question"] = lambda v, x, rng: (
    f"甲列车长{fmt_num(v['L1']['value'])}米以{fmt_num(v['v1']['value'])}米每秒行驶，"
    f"乙列车长{fmt_num(v['L2']['value'])}米以{fmt_num(v['v2']['value'])}米每秒行驶，两车同向而行（甲在后追乙），求超车时间。")


@spec(id="echo_problem", grade=5, topic="回声测距",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("train", "moving_object", "火车"),
                         E("wall", "object", "反射壁")])
def _t6(rng):
    v_tr = float(ri(rng, 5, 15) * 2)          # 偶数速 → 距离整数
    te = float(ri(rng, 1, 4))
    vs = 340.0
    d = (vs + v_tr) * te / 2
    v = {"v_train": V("火车速度", v_tr, "m/s"), "v_sound": V("声速", vs, "m/s"),
         "t_echo": V("回声时间", te, "s")}
    return v, d, None


_t6["steps"] = lambda v, x: [
    ("声音与火车2秒路程和", "(v_sound+v_train)*t_echo",
     "(params.v_sound+params.v_train)*params.t_echo", "m"),
    ("鸣笛处到反射壁距离", "results[1]/2", "results[1]/2", "m")]
_t6["question"] = lambda v, x, rng: (
    f"一列火车以{fmt_num(v['v_train']['value'])}米每秒的速度行驶时鸣笛，{fmt_num(v['t_echo']['value'])}秒后听到回声，"
    f"声速{fmt_num(v['v_sound']['value'])}米每秒，求鸣笛时火车距反射壁的距离。")


@spec(id="basic_motion", grade=6, topic="基本行程",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("car", "moving_object", "汽车")])
def _t7(rng):
    s, t = float(ri(rng, 5, 120)), float(ri(rng, 2, 60))
    return {"speed": V("速度", s, "m/s"), "time": V("时间", t, "s")}, s * t, None


_t7["steps"] = lambda v, x: [
    ("行驶路程", "speed*time", "params.speed*params.time", "m")]
_t7["question"] = lambda v, x, rng: f"一辆汽车以{fmt_num(v['speed']['value'])}米每秒的速度行驶了{fmt_num(v['time']['value'])}秒，行驶了多少米？"


@spec(id="cutting_segments", grade=3, topic="锯木头问题",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("wood", "object", "木头")])
def _t8(rng):
    n, tc = float(ri(rng, 2, 12)), float(ri(rng, 1, 5))
    return {"n_segments": V("段数", n, "段"),
            "time_per_cut": V("每次时间", tc, "分钟")}, (n - 1) * tc, None


_t8["steps"] = lambda v, x: [
    ("锯的次数", "n_segments-1", "params.n_segments-1", "次"),
    ("总时间", "results[1]*time_per_cut", "results[1]*params.time_per_cut", "分钟")]
_t8["question"] = lambda v, x, rng: (
    f"一根木头锯成{fmt_num(v['n_segments']['value'])}段，每锯一次需要{fmt_num(v['time_per_cut']['value'])}分钟，一共需要多少分钟？")


@spec(id="queue_counting", grade=1, topic="排队计数",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("person", "object", "小明")])
def _t9(rng):
    rf, rb = float(ri(rng, 2, 30)), float(ri(rng, 2, 30))
    return {"rank_front": V("从前数第", rf, "个"),
            "rank_behind": V("从后数第", rb, "个")}, rf + rb - 1, None


_t9["steps"] = lambda v, x: [
    ("前后相加", "rank_front+rank_behind", "params.rank_front+params.rank_behind", "人"),
    ("减去重复的自己", "results[1]-1", "results[1]-1", "人")]
_t9["question"] = lambda v, x, rng: (
    f"小明排队做操，从前面数他是第{fmt_num(v['rank_front']['value'])}个，从后面数他是第{fmt_num(v['rank_behind']['value'])}个，这一排共有多少人？")


@spec(id="overlap_splice", grade=1, topic="重叠拼接",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("board1", "object", "木板甲"),
                         E("board2", "object", "木板乙")])
def _t10(rng):
    a, b = float(ri(rng, 3, 20)), float(ri(rng, 3, 20))
    ov = float(ri(rng, 1, int(min(a, b) - 1)))
    return {"board1": V("甲板长", a, "cm"), "board2": V("乙板长", b, "cm"),
            "overlap": V("重叠长", ov, "cm")}, a + b - ov, None


_t10["steps"] = lambda v, x: [
    ("两板长度和", "board1+board2", "params.board1+params.board2", "cm"),
    ("拼接总长", "results[1]-overlap", "results[1]-params.overlap", "cm")]
_t10["question"] = lambda v, x, rng: (
    f"两块木板分别长{fmt_num(v['board1']['value'])}厘米和{fmt_num(v['board2']['value'])}厘米，"
    f"重叠{fmt_num(v['overlap']['value'])}厘米后钉成一块长木板，求拼成后的总长度。")


@spec(id="round_trip", grade=3, topic="往返路程",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("student", "moving_object", "学生")])
def _t11(rng):
    d, trips = float(ri(rng, 1, 90) * 10), float(ri(rng, 1, 4))
    return {"distance": V("单程", d, "m"), "trips": V("往返次数", trips, "次")}, d * 2 * trips, None


_t11["steps"] = lambda v, x: [
    ("一次往返", "distance*2", "params.distance*2", "m"),
    ("多次往返总路程", "results[1]*trips", "results[1]*params.trips", "m")]
_t11["question"] = lambda v, x, rng: (
    f"家到学校的距离是{fmt_num(v['distance']['value'])}米，小明每天往返{fmt_num(v['trips']['value'])}次，一共要走多少米？")


@spec(id="redundant_filter", grade=1, topic="干扰信息筛选",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("tree", "object", "树")])
def _t12(rng):
    total, removed = float(ri(rng, 5, 20)), float(ri(rng, 1, 4))
    return {"total": V("原有", total, "只"), "removed": V("飞走", removed, "只")}, total - removed, None


_t12["steps"] = lambda v, x: [
    ("剩下的数量", "total-removed", "params.total-params.removed", "只")]
_t12["question"] = lambda v, x, rng: (
    f"树上有{fmt_num(v['total']['value'])}只鸟，飞走了{fmt_num(v['removed']['value'])}只，"
    f"又飞来{fmt_num(ri(rng, 1, 5))}只蝴蝶，现在树上还剩几只鸟？")


@spec(id="fold_cut", grade=2, topic="对折剪绳",
      visual="track_timeline", fallback="flow_card",
      ents=lambda v, x: [E("rope", "object", "绳子")])
def _t13(rng):
    folds = float(ri(rng, 1, 3))
    return {"folds": V("对折次数", folds, "次")}, 2 ** int(folds) + 1, None


_t13["steps"] = lambda v, x: [
    ("剪成的段数", "2**folds+1", "2**params.folds+1", "段")]
_t13["question"] = lambda v, x, rng: (
    f"一根绳子对折{fmt_num(v['folds']['value'])}次后，从中间剪开，绳子被分成了几段？")


@spec(id="tree_planting", grade=4, topic="植树问题",
      visual="track_timeline", fallback="tape_diagram",
      ents=lambda v, x: [E("road", "object", "小路")])
def _t14(rng):
    mode = pick(rng, ["both_ends", "closed", "one_end", "neither"])
    spacing, seg = float(ri(rng, 2, 10)), float(ri(rng, 2, 40))
    length = spacing * seg
    trees = {"both_ends": seg + 1, "closed": seg, "one_end": seg,
             "neither": seg - 1}[mode]
    expr = {"both_ends": "params.length/params.spacing+1",
            "closed": "params.length/params.spacing",
            "one_end": "params.length/params.spacing",
            "neither": "params.length/params.spacing-1"}[mode]
    formula = {"both_ends": "length/spacing+1", "closed": "length/spacing",
               "one_end": "length/spacing", "neither": "length/spacing-1"}[mode]
    v = {"length": V("路长", length, "m"), "spacing": V("间距", spacing, "m")}
    _t14["steps"] = lambda vv, xx: [("棵数", formula, expr, "棵")]
    return v, trees, {"mode": mode}


_t14["steps"] = lambda v, x: [("棵数", "length/spacing+1", "params.length/params.spacing+1", "棵")]
_q14 = {
    "both_ends": lambda v: f"一条{fmt_num(v['length']['value'])}米的小路，每隔{fmt_num(v['spacing']['value'])}米栽一棵树（两端都栽），一共要栽多少棵？",
    "closed": lambda v: f"圆形花坛周长{fmt_num(v['length']['value'])}米，每隔{fmt_num(v['spacing']['value'])}米栽一棵树，一共要栽多少棵？",
    "one_end": lambda v: f"一条{fmt_num(v['length']['value'])}米的小路一旁植树，每隔{fmt_num(v['spacing']['value'])}米栽一棵（一端靠墙不栽），一共要栽多少棵？",
    "neither": lambda v: f"一段{fmt_num(v['length']['value'])}米的长廊，每隔{fmt_num(v['spacing']['value'])}米放一盆花（两端都不放），一共要放多少盆？",
}
_t14["question"] = lambda v, x, rng: _q14[x["mode"]](v)


@spec(id="fence_against_wall", grade=2, topic="靠墙围栏",
      visual="track_timeline", fallback="geometry_2d",
      ents=lambda v, x: [E("garden", "object", "菜园")])
def _t15(rng):
    length, width = float(ri(rng, 4, 20)), float(ri(rng, 2, 15))
    perim = 2 * width + length
    return {"length": V("长边", length, "m"),
            "perimeter": V("篱笆总长", perim, "m")}, length * width, None


_t15["steps"] = lambda v, x: [
    ("宽", "(perimeter-length)/2", "(params.perimeter-params.length)/2", "m"),
    ("面积", "length*results[1]", "params.length*results[1]", "平方米")]
_t15["question"] = lambda v, x, rng: (
    f"靠墙围一个长方形菜园，长边{fmt_num(v['length']['value'])}米靠墙，三边篱笆总长{fmt_num(v['perimeter']['value'])}米，求菜园的面积。")


# ── 比例/盈亏 (tape_diagram) ──

@spec(id="chicken_rabbit", grade=3, topic="鸡兔同笼",
      visual="tape_diagram", fallback="flow_card",
      ents=lambda v, x: [E("animals", "object", "鸡兔")])
def _t16(rng):
    heads = float(ri(rng, 5, 20))
    rabbits = float(ri(rng, 1, int(heads) - 1))
    legs = 4 * rabbits + 2 * (heads - rabbits)
    return {"heads": V("头数", heads, "个"), "legs": V("腿数", legs, "条")}, rabbits, None


_t16["steps"] = lambda v, x: [
    ("假设全鸡的腿数", "2*heads", "2*params.heads", "条"),
    ("腿数差", "legs-results[1]", "params.legs-results[1]", "条"),
    ("兔的只数", "results[2]/2", "results[2]/2", "只")]
_t16["question"] = lambda v, x, rng: (
    f"鸡兔同笼，共有{fmt_num(v['heads']['value'])}个头、{fmt_num(v['legs']['value'])}条腿，鸡兔各有几只？（求兔的只数）")


@spec(id="sum_multiple", grade=3, topic="和倍问题",
      visual="tape_diagram", fallback="flow_card",
      ents=lambda v, x: [E("a", "object", "甲"), E("b", "object", "乙")])
def _t17(rng):
    small, mult = float(ri(rng, 2, 30)), float(ri(rng, 2, 6))
    total = small + small * mult
    return {"sum": V("两数之和", total, ""), "multiple": V("倍数", mult, "倍")}, small * mult, None


_t17["steps"] = lambda v, x: [
    ("份数和", "multiple+1", "params.multiple+1", "份"),
    ("较小数", "sum/results[1]", "params.sum/results[1]", ""),
    ("较大数", "results[2]*multiple", "results[2]*params.multiple", "")]
_t17["question"] = lambda v, x, rng: (
    f"甲乙两数之和是{fmt_num(v['sum']['value'])}，甲是乙的{fmt_num(v['multiple']['value'])}倍，求甲（较大的数）。")


@spec(id="profit_loss", grade=5, topic="盈亏问题",
      visual="tape_diagram", fallback="bucket_divider",
      ents=lambda v, x: [E("people", "object", "小朋友")])
def _t18(rng):
    people = float(ri(rng, 4, 20))
    p1 = float(ri(rng, 3, 8))
    dv = float(ri(rng, 1, 4))
    p2 = p1 + dv
    surplus = float(ri(rng, 2, int(dv * people - 1)))
    deficit = dv * people - surplus
    v = {"surplus": V("盈余", surplus, "支"), "deficit": V("不足", deficit, "支"),
         "diff": V("两次分配差", p2 - p1, "支")}
    return v, people, None


_t18["steps"] = lambda v, x: [
    ("盈亏总和", "surplus+deficit", "params.surplus+params.deficit", "支"),
    ("人数", "results[1]/diff", "results[1]/params.diff", "人")]
_t18["question"] = lambda v, x, rng: (
    f"老师把一些笔分给小朋友，每人分{fmt_num(v['diff']['value']+2)}支则多{fmt_num(v['surplus']['value'])}支，"
    f"每人分{fmt_num(v['diff']['value']+4)}支则少{fmt_num(v['deficit']['value'])}支，一共有多少个小朋友？")


# ── 几何家族 ──

@spec(id="sprinkler_area", grade=3, topic="洒水车面积",
      visual="geometry_2d", fallback="track_timeline",
      ents=lambda v, x: [E("truck", "moving_object", "洒水车")])
def _t19(rng):
    s = float(ri(rng, 2, 20) * 10)
    w, t = float(ri(rng, 2, 8)), float(ri(rng, 2, 10))
    return {"speed": V("洒水车速度", s, "m/min"), "width": V("洒水宽度", w, "m"),
            "time": V("工作时间", t, "min")}, s * w * t, None


_t19["steps"] = lambda v, x: [
    ("行驶路程", "speed*time", "params.speed*params.time", "m"),
    ("洒水面积", "results[1]*width", "results[1]*params.width", "平方米")]
_t19["question"] = lambda v, x, rng: (
    f"一辆洒水车每分钟行驶{fmt_num(v['speed']['value'])}米，洒水宽度{fmt_num(v['width']['value'])}米，"
    f"洒水车工作{fmt_num(v['time']['value'])}分钟，被洒水的地面面积是多少平方米？")


@spec(id="displacement_volume", grade=5, topic="排水法求体积",
      visual="isometric_3d", fallback="flow_card",
      ents=lambda v, x: [E("tank", "container", "水箱"),
                         E("stone", "object", "石头")])
def _t20(rng):
    a, b = float(ri(rng, 8, 30)), float(ri(rng, 6, 20))
    rise = float(ri(rng, 1, 6))
    return {"length": V("水箱长", a, "cm"), "width": V("水箱宽", b, "cm"),
            "rise": V("水面上升", rise, "cm")}, a * b * rise, None


_t20["steps"] = lambda v, x: [
    ("底面积", "length*width", "params.length*params.width", "平方厘米"),
    ("石头体积", "results[1]*rise", "results[1]*params.rise", "立方厘米")]
_t20["question"] = lambda v, x, rng: (
    f"一个长{fmt_num(v['length']['value'])}厘米、宽{fmt_num(v['width']['value'])}厘米的水箱装有一些水，"
    f"放入一块石头后水面上升了{fmt_num(v['rise']['value'])}厘米，这块石头的体积是多少立方厘米？")


@spec(id="cuboid_combine_surface", grade=5, topic="长方体拼接表面积",
      visual="isometric_3d", fallback="geometry_2d",
      ents=lambda v, x: [E("box", "object", "长方体")])
def _t21(rng):
    a, b, c = float(ri(rng, 2, 9)), float(ri(rng, 2, 9)), float(ri(rng, 2, 9))
    sa = 2 * (a * b + a * c + b * c)
    min_face = min(a * b, a * c, b * c)
    faces = {"ab": (a, b), "ac": (a, c), "bc": (b, c)}
    k = min(faces, key=lambda k: faces[k][0] * faces[k][1])
    fa, fb = faces[k]
    return ({"length": V("长", a, "cm"), "width": V("宽", b, "cm"),
             "height": V("高", c, "cm")}, 2 * sa - min_face,
            {"fa": fa, "fb": fb})


_t21["steps"] = lambda v, x: [
    ("单个长方体表面积", "2*(length*width+length*height+width*height)",
     "2*(params.length*params.width+params.length*params.height+params.width*params.height)",
     "平方厘米"),
    ("两个拼后最大表面积", "results[1]*2", "results[1]*2", "平方厘米"),
    ("最大拼法表面积", "results[2]-fa*fb", "results[2]-params.height*params.width" if False
     else f"results[2]-{fmt_num(x['fa'])}*{fmt_num(x['fb'])}", "平方厘米")]
_t21["question"] = lambda v, x, rng: (
    f"两个长{fmt_num(v['length']['value'])}厘米、宽{fmt_num(v['width']['value'])}厘米、高{fmt_num(v['height']['value'])}厘米的长方体拼成一个大长方体，"
    f"拼成的长方体表面积最大是多少平方厘米？")


@spec(id="semicircle_perimeter", grade=6, topic="半圆周长",
      visual="geometry_2d", fallback="tape_diagram",
      ents=lambda v, x: [E("semicircle", "object", "半圆")])
def _t22(rng):
    r = float(ri(rng, 1, 12))
    return {"radius": V("半径", r, "cm")}, PI * r + 2 * r, None


_t22["steps"] = lambda v, x: [
    ("圆弧长", "3.14*radius", "3.14*params.radius", "cm"),
    ("半圆周长", "results[1]+2*radius", "results[1]+2*params.radius", "cm")]
_t22["question"] = lambda v, x, rng: f"一个半圆的半径是{fmt_num(v['radius']['value'])}厘米，它的周长是多少厘米？（π取3.14）"


@spec(id="rectangle_area", grade=3, topic="长方形面积",
      visual="geometry_2d", fallback="tape_diagram",
      ents=lambda v, x: [E("rect", "object", "长方形")])
def _t23(rng):
    a, b = float(ri(rng, 3, 30)), float(ri(rng, 2, 20))
    return {"length": V("长", a, "cm"), "width": V("宽", b, "cm")}, a * b, None


_t23["steps"] = lambda v, x: [
    ("面积", "length*width", "params.length*params.width", "平方厘米")]
_t23["question"] = lambda v, x, rng: (
    f"一个长方形的长是{fmt_num(v['length']['value'])}厘米，宽是{fmt_num(v['width']['value'])}厘米，它的面积是多少平方厘米？")


@spec(id="cylinder_cone_cut", grade=6, topic="圆柱圆锥",
      visual="isometric_3d", fallback="geometry_2d",
      ents=lambda v, x: [E("cyl", "container", "圆柱")])
def _t24(rng):
    r = float(ri(rng, 1, 6) * 2)
    h = float(ri(rng, 3, 20))
    vol = PI * r * r * h
    # 问"截去圆锥后剩余"或"圆柱体积" — 取圆柱体积整数化 (r 偶数保 π 整除)
    return {"radius": V("底面半径", r, "cm"), "height": V("高", h, "cm")}, vol, None


_t24["steps"] = lambda v, x: [
    ("底面积", "3.14*radius*radius", "3.14*params.radius*params.radius", "平方厘米"),
    ("圆柱体积", "results[1]*height", "results[1]*params.height", "立方厘米")]
_t24["question"] = lambda v, x, rng: (
    f"一个圆柱形水桶，底面半径{fmt_num(v['radius']['value'])}厘米，高{fmt_num(v['height']['value'])}厘米，"
    f"它的容积是多少立方厘米？（π取3.14）")


# ── 统计/平均 ──

@spec(id="average_problem", grade=4, topic="平均数",
      visual="data_chart", fallback="flow_card",
      ents=lambda v, x: [E("scores", "data", "成绩")])
def _t25(rng):
    cnt = float(ri(rng, 3, 6))
    vals = [ri(rng, 60, 100) for _ in range(int(cnt))]
    total = sum(vals)
    return {"total_sum": V("总分", total, "分"), "count": V("科目数", cnt, "科")}, total / cnt, None


_t25["steps"] = lambda v, x: [
    ("平均分", "total_sum/count", "params.total_sum/params.count", "分")]
_t25["question"] = lambda v, x, rng: (
    f"小明{fmt_num(v['count']['value'])}次数学成绩的总分是{fmt_num(v['total_sum']['value'])}分，他平均每次考多少分？")


@spec(id="statistics_mean", grade=4, topic="统计平均",
      visual="data_chart", fallback="flow_card",
      ents=lambda v, x: [E("group", "data", "小组")])
def _t26(rng):
    n = float(ri(rng, 4, 10))
    mean = float(ri(rng, 5, 30))
    return {"count": V("人数", n, "人"), "average": V("平均每人的个数", mean, "个")}, n * mean, None


_t26["steps"] = lambda v, x: [
    ("总个数", "count*average", "params.count*params.average", "个")]
_t26["question"] = lambda v, x, rng: (
    f"一组{fmt_num(v['count']['value'])}名同学平均每人收集{fmt_num(v['average']['value'])}个空瓶，这组同学一共收集了多少个空瓶？")


@spec(id="equal_division", grade=2, topic="平均分",
      visual="bucket_divider", fallback="flow_card",
      ents=lambda v, x: [E("items", "object", "糖果"),
                         E("kids", "object", "小朋友")])
def _t27(rng):
    kids, per = float(ri(rng, 2, 9)), float(ri(rng, 2, 12))
    return {"kids": V("小朋友数", kids, "人"), "per": V("每人分到", per, "颗")}, kids * per, None


_t27["steps"] = lambda v, x: [
    ("糖果总数", "kids*per", "params.kids*params.per", "颗")]
_t27["question"] = lambda v, x, rng: (
    f"有{fmt_num(v['kids']['value'])}个小朋友，平均每人分到{fmt_num(v['per']['value'])}颗糖果，一共有多少颗糖果？")


# ── 归一/单价/阶梯/工程 ──

@spec(id="unitary_method", grade=3, topic="归一问题",
      visual="flow_card", fallback="tape_diagram",
      ents=lambda v, x: [E("books", "object", "笔记本")])
def _t28(rng):
    n1 = float(ri(rng, 2, 8))
    unit = float(ri(rng, 2, 15))
    n2 = float(ri(rng, 3, 12))
    return {"n_items": V("本数", n1, "本"), "total_value": V("总价", n1 * unit, "元"),
            "n_target": V("要买本数", n2, "本")}, n2 * unit, None


_t28["steps"] = lambda v, x: [
    ("单价", "total_value/n_items", "params.total_value/params.n_items", "元"),
    ("目标总价", "results[1]*n_target", "results[1]*params.n_target", "元")]
_t28["question"] = lambda v, x, rng: (
    f"{fmt_num(v['n_items']['value'])}本笔记本共{fmt_num(v['total_value']['value'])}元，"
    f"买{fmt_num(v['n_target']['value'])}本这样的笔记本需要多少元？")


@spec(id="unitary_combined", grade=4, topic="归总问题",
      visual="flow_card", fallback="tape_diagram",
      ents=lambda v, x: [E("workers", "object", "工人")])
def _t29(rng):
    np1, nd1 = float(ri(rng, 2, 8)), float(ri(rng, 3, 10))
    per = float(ri(rng, 2, 15))
    total = np1 * nd1 * per
    np2, nd2 = np1 + ri(rng, 1, 4), float(ri(rng, 2, 8))
    # expect = 末步值 (target_people × target_days × per) — gate4 对齐
    return ({"n_people": V("人数", np1, "人"), "n_days": V("天数", nd1, "天"),
             "total_work": V("零件总数", total, "个"),
             "target_people": V("后来人数", np2, "人"),
             "target_days": V("后来天数", nd2, "天")}, per * np2 * nd2, None)


_t29["steps"] = lambda v, x: [
    ("每人每天做的个数", "total_work/(n_people*n_days)",
     "params.total_work/(params.n_people*params.n_days)", "个"),
    ("8人3天做的个数", "results[1]*target_people*target_days",
     "results[1]*params.target_people*params.target_days", "个")]
_t29["question"] = lambda v, x, rng: (
    f"{fmt_num(v['n_people']['value'])}名工人{fmt_num(v['n_days']['value'])}天共生产{fmt_num(v['total_work']['value'])}个零件，"
    f"照这样计算，{fmt_num(v['target_people']['value'])}名工人{fmt_num(v['target_days']['value'])}天能生产多少个零件？")


@spec(id="work_problem", grade=5, topic="工程合作",
      visual="flow_card", fallback="tape_diagram",
      ents=lambda v, x: [E("a", "object", "甲"), E("b", "object", "乙")])
def _t30(rng):
    d1 = float(ri(rng, 2, 15))
    d2 = d1 + ri(rng, 1, 15)
    days = d1 * d2 / (d1 + d2)
    return ({"worker1_days": V("甲单独天数", d1, "天"),
             "worker2_days": V("乙单独天数", d2, "天")}, days, None)


_t30["steps"] = lambda v, x: [
    ("甲的效率", "1/worker1_days", "1/params.worker1_days", "1/天"),
    ("乙的效率", "1/worker2_days", "1/params.worker2_days", "1/天"),
    ("合作天数", "1/(results[1]+results[2])", "1/(results[1]+results[2])", "天")]
_t30["question"] = lambda v, x, rng: (
    f"一项工程甲单独做{fmt_num(v['worker1_days']['value'])}天完成，乙单独做{fmt_num(v['worker2_days']['value'])}天完成，"
    f"两人合作需要多少天完成？（结果保留两位小数）")


@spec(id="tiered_pricing", grade=3, topic="阶梯计价",
      visual="flow_card", fallback="data_chart",
      ents=lambda v, x: [E("taxi", "moving_object", "出租车")])
def _t31(rng):
    base_d = float(ri(rng, 2, 4))
    base_p = float(ri(rng, 5, 12))
    unit_p = float(ri(rng, 1, 4))
    extra = float(ri(rng, 1, 12))
    return ({"base_distance": V("起步里程", base_d, "千米"),
             "base_price": V("起步价", base_p, "元"),
             "unit_price": V("超出单价", unit_p, "元/千米"),
             "total_distance": V("行驶里程", base_d + extra, "千米")},
            base_p + extra * unit_p, None)


_t31["steps"] = lambda v, x: [
    ("超出里程", "total_distance-base_distance",
     "params.total_distance-params.base_distance", "千米"),
    ("超出部分费用", "results[1]*unit_price", "results[1]*params.unit_price", "元"),
    ("总费用", "results[2]+base_price", "results[2]+params.base_price", "元")]
_t31["question"] = lambda v, x, rng: (
    f"出租车{fmt_num(v['base_distance']['value'])}千米以内收起步价{fmt_num(v['base_price']['value'])}元，"
    f"超出部分每千米{fmt_num(v['unit_price']['value'])}元。小华乘出租车行了{fmt_num(v['total_distance']['value'])}千米，应付多少元？")


@spec(id="weekday_calc", grade=3, topic="星期推算",
      visual="flow_card", fallback="track_timeline",
      ents=lambda v, x: [E("calendar", "object", "日历")])
def _t32(rng):
    start = float(ri(rng, 1, 7))          # 1=周一 … 7=周日
    rem = float(ri(rng, 0, 6))            # add_days ≡ rem (mod 7)
    weeks = float(ri(rng, 1, 8))
    add = weeks * 7 + rem
    total = start + rem
    if total <= 7:
        target, branch = total, "same_week"
    else:
        target, branch = total - 7, "cross_week"
    return ({"start_day": V("起始星期", start, "号"),
             "add_days": V("经过天数", add, "天"),
             "weeks": V("整周数", weeks, "周"),
             "remainder": V("余数天数", rem, "天")}, target, {"branch": branch})


_t32["steps"] = lambda v, x: (
    [("目标星期", "start_day+remainder", "params.start_day+params.remainder", "号")]
    if x["branch"] == "same_week" else
    [("推过整周后的星期", "start_day+remainder", "params.start_day+params.remainder", "号"),
     ("目标星期", "results[1]-7", "results[1]-7", "号")])
# add_days/weeks 是题面语境参数 (分解已在题干给出), eval 合法地只引用 start_day/remainder
_t32["allow_unused"] = True
_t32["question"] = lambda v, x, rng: (
    f"今天是星期{fmt_num(v['start_day']['value'])}（按周一为1、周日为7编号），"
    f"再过{fmt_num(v['add_days']['value'])}天（{fmt_num(v['weeks']['value'])}周零{fmt_num(v['remainder']['value'])}天）是星期几？")


@spec(id="simple_interest", grade=6, topic="单利利息",
      visual="flow_card", fallback="tape_diagram",
      ents=lambda v, x: [E("bank", "object", "银行")])
def _t33(rng):
    principal = float(ri(rng, 2, 40) * 100)
    rate_pct = float(ri(rng, 1, 5))
    years = float(ri(rng, 1, 5))
    return ({"principal": V("本金", principal, "元"),
             "rate": V("年利率", rate_pct, "%"),
             "years": V("存期", years, "年")}, principal * rate_pct / 100 * years, None)


_t33["steps"] = lambda v, x: [
    ("每年利息", "principal*rate/100", "params.principal*params.rate/100", "元"),
    ("总利息", "results[1]*years", "results[1]*params.years", "元")]
_t33["question"] = lambda v, x, rng: (
    f"王叔叔把{fmt_num(v['principal']['value'])}元存入银行，年利率{fmt_num(v['rate']['value'])}%，存{fmt_num(v['years']['value'])}年，到期时利息是多少元？（单利）")


# ── 阵列/组合/方程/四则 (array_grid / flow_card) ──

@spec(id="array_counting", grade=2, topic="乘法阵列",
      visual="array_grid", fallback="flow_card",
      ents=lambda v, x: [E("grid", "object", "方阵")])
def _t34(rng):
    rows, cols = float(ri(rng, 2, 9)), float(ri(rng, 2, 9))
    return {"rows": V("行数", rows, "行"), "cols": V("列数", cols, "列")}, rows * cols, None


_t34["steps"] = lambda v, x: [
    ("总数", "rows*cols", "params.rows*params.cols", "个")]
_t34["question"] = lambda v, x, rng: (
    f"操场上做操的队伍有{fmt_num(v['rows']['value'])}行，每行{fmt_num(v['cols']['value'])}人，一共有多少人？")


@spec(id="combination_count", grade=6, topic="搭配组合",
      visual="flow_card", fallback="array_grid",
      ents=lambda v, x: [E("tops", "object", "上衣"),
                         E("pants", "object", "裤子")])
def _t35(rng):
    a, b = float(ri(rng, 2, 5)), float(ri(rng, 2, 5))
    return {"n_items1": V("上衣件数", a, "件"),
            "n_items2": V("裤子条数", b, "条")}, a * b, None


_t35["steps"] = lambda v, x: [
    ("搭配种数", "n_items1*n_items2", "params.n_items1*params.n_items2", "种")]
_t35["question"] = lambda v, x, rng: (
    f"小丽有{fmt_num(v['n_items1']['value'])}件上衣和{fmt_num(v['n_items2']['value'])}条裤子，一件上衣和一条裤子配成一套，共有多少种不同的搭配？")


@spec(id="arithmetic", grade=3, topic="四则运算",
      visual="flow_card", fallback="data_chart",
      ents=lambda v, x: [E("calc", "object", "计算")])
def _t36(rng):
    a, b, c = float(ri(rng, 10, 99)), float(ri(rng, 2, 9)), float(ri(rng, 2, 20))
    # (a+b)*c 或 a+b*c — 保证结果整洁
    if rng.random() < 0.5:
        return ({"a": V("第一个数", a, ""), "b": V("第二个数", b, ""),
                 "c": V("第三个数", c, "")}, (a + b) * c, {"pat": 1})
    return ({"a": V("第一个数", a, ""), "b": V("第二个数", b, ""),
             "c": V("第三个数", c, "")}, a + b * c, {"pat": 2})


_t36["steps"] = lambda v, x: (
    [("和", "a+b", "params.a+params.b", ""),
     ("积", "results[1]*c", "results[1]*params.c", "")]
    if x["pat"] == 1 else
    [("积", "b*c", "params.b*params.c", ""),
     ("和", "a+results[1]", "params.a+results[1]", "")])
_t36["question"] = lambda v, x, rng: (
    f"计算：{fmt_num(v['a']['value'])} 加 {fmt_num(v['b']['value'])} 的和再乘 {fmt_num(v['c']['value'])} 是多少？"
    if x["pat"] == 1 else
    f"计算：{fmt_num(v['a']['value'])} 加上 {fmt_num(v['b']['value'])} 乘 {fmt_num(v['c']['value'])} 的积，结果是多少？")


@spec(id="linear_equation", grade=5, topic="一元一次方程",
      visual="flow_card", fallback="tape_diagram",
      ents=lambda v, x: [E("eq", "object", "方程")])
def _t37(rng):
    x = float(ri(rng, 2, 30))
    k = float(ri(rng, 2, 9))
    b = float(ri(rng, 1, 40))
    return {"k": V("系数", k, ""), "b": V("常数项", b, ""),
            "target_value": V("方程结果", k * x + b, "")}, x, None


_t37["steps"] = lambda v, x: [
    ("移项", "target_value-b", "params.target_value-params.b", ""),
    ("求解", "results[1]/k", "results[1]/params.k", "")]
_t37["question"] = lambda v, x, rng: (
    f"解方程：{fmt_num(v['k']['value'])}x + {fmt_num(v['b']['value'])} = {fmt_num(v['target_value']['value'])}，求 x。")


@spec(id="stars_bars", grade=5, topic="隔板法",
      visual="flow_card", fallback="array_grid",
      ents=lambda v, x: [E("items", "object", "糖果"),
                         E("bins", "object", "篮子")])
def _t38(rng):
    # 公式 (m+k-1)*(m+k-2)*.../(k-1)! 在受限求值器里只能展开为有限四则 —
    # 固定 3 篮: ways = m*(m+1)/2 + (m+1), 3 篮时 C(m+2,2)=(m+2)(m+1)/2, m≥1
    n_bins = 3.0
    min_per = float(ri(rng, 1, 3))
    n_items = int(min_per * n_bins + ri(rng, 1, 8))
    import math
    m = n_items - int(min_per) * int(n_bins)   # 自由糖果
    ways = math.comb(m + 2, 2)
    return ({"n_items": V("糖果数", n_items, "颗"),
             "n_bins": V("篮子数", n_bins, "个"),
             "min_per": V("每篮至少", min_per, "颗")}, ways, {"m": m})


_t38["steps"] = lambda v, x: [
    ("剩余自由糖果", "n_items-min_per*n_bins", "params.n_items-params.min_per*params.n_bins", "颗"),
    ("放法数", "(results[1]+1)*(results[1]+2)/2", "(results[1]+1)*(results[1]+2)/2", "种")]
_t38["allow_unused"] = True
_t38["question"] = lambda v, x, rng: (
    f"把{fmt_num(v['n_items']['value'])}颗相同的糖果全部分给{fmt_num(v['n_bins']['value'])}个不同的篮子，"
    f"每个篮子至少{fmt_num(v['min_per']['value'])}颗，有多少种不同的放法？")


# ────────────────────────── 主流程 ──────────────────────────

def synth_one(sid: str, sp: dict, rng: random.Random) -> dict | None:
    """生成一条样本, 四道闸任一失败返回 None (计数在调用方)。"""
    vars_d, expect, extra = sp["gen"](rng)
    steps = sp["steps"](vars_d, extra)
    ents = sp["ents"](vars_d, extra)
    pipe = build_pipeline(ents, steps)
    dsl = {
        "meta": {"id": sid, "grade": sp["grade"], "topic": sp["topic"],
                 "visual_type": sp["visual"],
                 "fallback_type": fallback_for(sp["visual"])},
        "parameters": vars_d,
        "entities": ents,
        "pipeline": pipe,
    }
    step_vals, _why = check_gates(dsl, vars_d, steps, expect, sp["allow_unused"])
    if step_vals is None:
        return None
    thinking = build_thinking(sp["topic"], vars_d, steps, step_vals)
    return {
        "question": sp["question"](vars_d, extra, rng),
        "thinking": thinking,
        "dsl": dsl,
        "template_id": sp["id"],
        "grade": sp["grade"],
        "category": "in_domain",
        "ground_truth": round(float(expect), 4),
        "gate4_computed": round(step_vals[len(steps)], 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=4000)
    ap.add_argument("--holdout", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/bnup/raw_sft_v1.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out: list[dict] = []
    gate_fail = 0
    attempts = 0
    max_attempts = args.total * 8
    # 均匀轮转模板 (每模板配额), 模板数 ~30 → 每模板 ~total/len(SPEC)
    quota = args.total // len(SPEC) + 1
    counters: dict[str, int] = {}
    while len(out) < args.total and attempts < max_attempts:
        attempts += 1
        sp = pick(rng, SPEC)
        if counters.get(sp["id"], 0) >= quota:
            continue
        sid = f"syn-{sp['id']}-{counters.get(sp['id'], 0) + 1:04d}"
        rec = synth_one(sid, sp, rng)
        if rec is None:
            gate_fail += 1
            continue
        counters[sp["id"]] = counters.get(sp["id"], 0) + 1
        out.append(rec)
    if len(out) < args.total:
        raise SystemExit(f"FATAL: 尝试 {attempts} 次仅产出 {len(out)}/{args.total} (四道闸拒绝 {gate_fail}) — 模板有 bug, 拒绝降质量交付")

    # 留出集拆分
    rng.shuffle(out)
    holdout = out[: args.holdout]
    for r in out:
        r["split"] = "holdout" if r in holdout else "train"

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    by_t = {}
    for r in out:
        by_t[r["template_id"]] = by_t.get(r["template_id"], 0) + 1
    print(f"产出 {len(out)} 条 (train {len(out)-args.holdout} / holdout {args.holdout})")
    print(f"四道闸拒绝: {gate_fail} (目标 0)")
    print(f"模板覆盖: {len(by_t)}/{len(SPEC)}")
    print(f"→ {outp}")


if __name__ == "__main__":
    main()

