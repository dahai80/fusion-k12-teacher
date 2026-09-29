"""数学场景动画编译器 — LLM 结构化提取 → SymPy 覆写 → SceneDSL (PRD §4)。

三段式流水线 (严禁 LLM 直接生成绘图代码/视频):
1. LLM 提取 scenario/entities/units/key_milestones/question_focus (Structured Output)。
2. MathSympyVerifier 按场景公式覆写数值 (Single Source of Truth)。
3. 输出 SceneDSL (course.models, 学科中立) 供前端模板渲染。

降级: 未命中模板 → 静态示意图 + KaTeX 分步推导 (PRD M5-B01)。
"""

from __future__ import annotations

import logging
from typing import Any

from ...._parse import parse_json
from ....ai_client import MLXClient
from ....errors import rethrow_if_fatal
from ....safety.filter import sanitize_input
from ...base import SceneCompilerBase
from ...models import Milestone, SceneDSL, SceneEntity, VerifyResult
from . import generic_pipeline
from .sympy_verifier import UNKNOWN_VARS, MathSympyVerifier

logger = logging.getLogger(__name__)

_KNOWN_SCENARIOS = (
    "train_crossing_bridge", "train_on_bridge", "relative_motion",
    "two_trains_meet", "two_trains_overtake", "echo_problem",
    "cutting_segments",
    "queue_counting", "fence_against_wall", "unitary_method",
    "chicken_rabbit", "basic_motion", "work_problem", "average_problem",
    "overlap_splice", "round_trip", "sum_multiple", "sprinkler_area",
    "tree_planting", "displacement_volume", "profit_loss",
    "simple_interest", "tiered_pricing", "weekday_calc",
    "semicircle_perimeter", "cuboid_combine_surface",
    "combination_count", "unitary_combined",
    "redundant_filter", "fold_cut", "stars_bars",
    "chase_meet", "plant_interval", "tank_water",
)

_EXTRACT_PROMPT = """你是数学应用题结构化提取器。从题目文本提取参数, 严格输出 JSON。

已知场景类型: {scenarios}

场景说明:
- train_crossing_bridge / train_on_bridge: 火车过桥/在桥上 (entities 含 bridge.length, train.length, train.speed)
- two_trains_meet / two_trains_overtake: 两车相遇/追及 (entities 含 train1/train2 的 length+speed)
- relative_motion: 人车相对运动 (entities 含 train.length+speed, pedestrian.speed)
- echo_problem: 回声测距 (entities 含 train.speed, v_sound=340, t_echo)
- cutting_segments: 锯木头/剪绳子/爬楼梯等离散计数题 (entities 含 object.n_segments=段数, object.time_per_cut=每次耗时) 注意: 对折后从中间剪开不是此场景, 用 fold_cut
- queue_counting: 排队计数 (从前数第a, 从后数第b, 求总人数) (entities 含 person.rank_front=从前位次, person.rank_behind=从后位次)
- fence_against_wall: 靠墙围篱笆 (长边靠墙, 三边围栏总长求面积) (entities 含 fence.length=靠墙长, fence.perimeter=三边总长)
- unitary_method: 归一问题 (a件b元, 求c件几元) (entities 含 group.n_items=件数, group.total_value=总价, group.n_target=目标件数)
- chicken_rabbit: 鸡兔同笼 (头数腿数求各几只, 鸡2腿兔4腿, 腿数远大于头数) (entities 含 cage.heads=头数, cage.legs=腿数) 注意: 鸟飞走/飞来不是鸡兔同笼
- basic_motion: 基本行程 路程=速度×时间 (entities 含 traveler.distance, traveler.speed, traveler.time, 给两个求第三个, 缺项填0)
- work_problem: 工程问题 (甲a天乙b天合作几天) (entities 含 worker1.days=甲天数, worker2.days=乙天数)
- average_problem: 平均数 (总和÷个数) (entities 含 data.total_sum=总和, data.count=个数)
- overlap_splice: 重叠拼接 (两板重叠1cm求总长) (entities 含 board.board1=板1长, board.board2=板2长, board.overlap=重叠长)
- round_trip: 往返路程 (去+回, 漏乘2) (entities 含 trip.distance=单程, trip.trips=往返次数)
- sum_multiple: 和倍问题 (甲乙和, 甲是乙几倍) (entities 含 pair.sum=和, pair.multiple=倍数)
- sprinkler_area: 洒水车面积 (长方形随时间扩大) (entities 含 sprinkler.speed=速度, sprinkler.width=宽, sprinkler.time=时间)
- tree_planting: 植树问题四类型 (两端栽/一端/两端不栽/封闭) (entities 含 road.length=路长, road.spacing=间距, road.mode_code=1两端栽/2一端/3两端不栽/0封闭)
- displacement_volume: 排水法求体积 (不规则物放入水箱水位上升) (entities 含 tank.length=水箱长, tank.width=水箱宽, tank.rise=上升高)
- profit_loss: 盈亏问题 (每人分a多b, 分c少d求人数) (entities 含 allocation.surplus=盈, allocation.deficit=亏, allocation.diff=每人分配数之差如c-a)
- simple_interest: 单利利息 (本金×年利率×年数) (entities 含 deposit.principal=本金, deposit.rate=年利率(小数如0.02), deposit.years=年数)
- tiered_pricing: 分段计费 (出租车起步价+超出单价) (entities 含 trip.base_distance=起步距离, trip.base_price=起步价, trip.unit_price=超出单价, trip.total_distance=总距离)
- weekday_calc: 星期推算 (今天周a, 再过b天是星期几) (entities 含 cal.start_day=今天星期数1-7, cal.add_days=过几天)
- semicircle_perimeter: 半圆周长 (弧长+直径) (entities 含 shape.radius=半径) 注意: 题目必须明确问"半圆/半圆形", 整圆周长/圆面积不是此场景
- cuboid_combine_surface: 长方体拼接表面积 (两相同长方体拼大长方体求最大/最小表面积) (entities 含 box.length, box.width, box.height) 注意: 仅限"拼/接后求表面积", 求周长/切割正方体求增加表面积均不是此场景 (切割正方体表面积增加无对应场景时填 unknown)
- combination_count: 搭配问题 (a件上衣b条裤子几种搭配) (entities 含 set.n_items1=上衣数, set.n_items2=裤子数)
- unitary_combined: 归一归总混合 (a人b天做c个, 求d人e天做多少) (entities 含 work.n_people, work.n_days, work.total_work, work.target_people, work.target_days)
- redundant_filter: 多余条件筛选题 (含干扰数字不参与运算, 如树上鸟飞走几只又飞来几朵花, 花与鸟无关) (entities 含 scene.total=有效总数如鸟数, scene.removed=减少数如飞走, scene.distraction=干扰数如花朵不参与运算)
- fold_cut: 对折剪开段数 (绳子/纸对折n次后从中间剪开, 段数=2^n+1, 非锯木头非简单乘法, 关键词"对折""从中间剪开") (entities 含 rope.folds=对折次数)
- stars_bars: 隔板法/整数分拆/相同物品放不同容器 (n个相同物品放k个不同容器每个至少min_per个求放法数, 每篮≥1用C(n-1,k-1), 每篮≥m先预留m*k再用C(n-m*k+k-1,k-1), 关键词"放法/放进/篮子/盒子/盘子/每个至少/最少分到/几种分法/隔板法/整数分拆", 如7根棒棒糖放3个篮子每篮≥1, 或12块巧克力分3人每人至少3块) (entities 含 bag.n_items=物品数, bag.n_bins=容器数, bag.min_per=每容器最少(默认1, 题目说"每个至少1"填1, "最少3块"填3))

输出 JSON 格式:
{{
  "scenario": "场景ID(必须从已知列表选, 无法匹配填 unknown)",
  "units": {{"distance": "m", "speed": "m/s", "time": "s"}},
  "entities": {{
    "bridge": {{"length": 数值, "label": "大桥"}},
    "train": {{"length": 数值, "speed": 数值, "label": "火车"}},
    "object": {{"n_segments": 数值, "time_per_cut": 数值, "label": "木头"}},
    "person": {{"rank_front": 数值, "rank_behind": 数值, "label": "小明"}},
    "fence": {{"length": 数值, "perimeter": 数值, "label": "篱笆"}},
    "group": {{"n_items": 数值, "total_value": 数值, "n_target": 数值, "label": "商品"}},
    "cage": {{"heads": 数值, "legs": 数值, "label": "笼"}},
    "traveler": {{"distance": 数值, "speed": 数值, "time": 数值, "label": "行人"}},
    "worker1": {{"days": 数值, "label": "甲"}},
    "worker2": {{"days": 数值, "label": "乙"}},
    "data": {{"total_sum": 数值, "count": 数值, "label": "数据"}},
    "board": {{"board1": 数值, "board2": 数值, "overlap": 数值, "label": "木板"}},
    "trip": {{"distance": 数值, "trips": 数值, "label": "往返"}},
    "pair": {{"sum": 数值, "multiple": 数值, "label": "甲乙"}},
    "sprinkler": {{"speed": 数值, "width": 数值, "time": 数值, "label": "洒水车"}},
    "road": {{"length": 数值, "spacing": 数值, "mode_code": 数值, "label": "路"}},
    "tank": {{"length": 数值, "width": 数值, "rise": 数值, "label": "水箱"}},
    "allocation": {{"surplus": 数值, "deficit": 数值, "diff": 数值, "label": "分配"}},
    "deposit": {{"principal": 数值, "rate": 数值, "years": 数值, "label": "存款"}},
    "trip2": {{"base_distance": 数值, "base_price": 数值, "unit_price": 数值, "total_distance": 数值, "label": "出租"}},
    "cal": {{"start_day": 数值, "add_days": 数值, "label": "日历"}},
    "shape": {{"radius": 数值, "label": "半圆"}},
    "box": {{"length": 数值, "width": 数值, "height": 数值, "label": "长方体"}},
    "set": {{"n_items1": 数值, "n_items2": 数值, "label": "搭配"}},
    "work2": {{"n_people": 数值, "n_days": 数值, "total_work": 数值, "target_people": 数值, "target_days": 数值, "label": "工程"}},
    "scene": {{"total": 数值, "removed": 数值, "distraction": 数值, "label": "场景"}},
    "rope": {{"folds": 数值, "label": "绳子"}},
    "bag": {{"n_items": 数值, "n_bins": 数值, "min_per": 数值(必须填, 题目说"每个至少1"或未提最少填1, "最少3块"/"至少3"填3), "label": "分放"}}
  }},
  "key_milestones": [
    {{"time_ratio": 0.0, "label": "车头上桥", "event": "start_bridge"}}
  ],
  "question_focus": "求解目标",
  "misconception_hint": "本题易错点(一句话)"
}}

只含与本题相关的 entities, 不相关字段留空或省略。

重要: 若题目是概念判断/性质辨析/读法规范/单位换算/是否题/几何性质变化等无法精确数值化求解的题 (如"对不对/够不够/怎么变/几时几分/保留几位小数/最大正方形周长思路"), scenario 填 "unknown", 不要勉强归入数值场景。只对能提取明确数值参数并求解的应用题归入对应场景。

题目: {problem}

只输出 JSON, 不要解释。"""


class MathSceneCompiler(SceneCompilerBase):
    """题目 → 结构化 JSON → SymPy 覆写 → SceneDSL。"""

    def __init__(self, mlx: MLXClient, verifier: MathSympyVerifier, content_filter=None) -> None:
        self.mlx = mlx
        self.verifier = verifier
        self.content_filter = content_filter

    async def compile(self, problem_text: str, knowledge_node_id: str = "") -> SceneDSL:
        problem = sanitize_input(problem_text)[:1000]
        prompt = _EXTRACT_PROMPT.format(scenarios=", ".join(_KNOWN_SCENARIOS), problem=problem)
        try:
            raw = await self.mlx.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1024)
        except Exception as exc:
            logger.warning("scene_compiler: LLM 提取失败 %s", exc)
            rethrow_if_fatal(exc)
            # 提取异常同样先尝试通用路径 (issue: 新题型全部降级), 失败才降级静态
            generic = await self._compile_generic(problem, knowledge_node_id)
            if generic is not None:
                return generic
            return SceneDSL(subject="math", meta={"original_text": problem}, error=f"LLM 提取失败: {exc}", fallback=True)

        extracted = parse_json(raw)
        if not extracted or not isinstance(extracted, dict):
            generic = await self._compile_generic(problem, knowledge_node_id)
            if generic is not None:
                return generic
            return SceneDSL(subject="math", meta={"original_text": problem}, error="LLM 输出非 JSON", fallback=True)

        scenario = str(extracted.get("scenario", "unknown"))
        entities_raw = extracted.get("entities", {})
        if not isinstance(entities_raw, dict):
            entities_raw = {}

        var_map = self._flatten_entities(scenario, entities_raw)
        verify = self.verifier.verify_scene(scenario, var_map) if scenario in _KNOWN_SCENARIOS else None

        if verify and verify.error and "未知场景" not in verify.error:
            logger.info("scene_compiler: 首次校验失败 %s, 重提一次", verify.error)
            try:
                raw2 = await self.mlx.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1024)
                extracted2 = parse_json(raw2)
                if isinstance(extracted2, dict):
                    var_map = self._flatten_entities(scenario, extracted2.get("entities", {}))
                    verify = self.verifier.verify_scene(scenario, var_map)
            except Exception as exc2:
                logger.warning("scene_compiler: 重提失败 %s", exc2)

        entities_list = self._build_entities_list(entities_raw, verify)
        milestones = self._build_milestones(extracted.get("key_milestones", []), verify, scenario)
        total_distance = self._var_value(verify, "S_total")
        total_time = self._var_value(verify, "t")
        if scenario == "cutting_segments":
            total_time = self._var_value(verify, "total_time") or total_time
        elif scenario == "queue_counting":
            total_distance = self._var_value(verify, "total_people")
            total_time = total_distance or 0.0
        elif scenario == "fence_against_wall":
            total_distance = self._var_value(verify, "area")
            total_time = self._var_value(verify, "width")
        elif scenario == "unitary_method":
            total_distance = self._var_value(verify, "target_value")
            total_time = self._var_value(verify, "unit_value")
        elif scenario == "chicken_rabbit":
            total_distance = self._var_value(verify, "rabbit")
            total_time = self._var_value(verify, "chicken")
        elif scenario == "basic_motion":
            total_distance = self._var_value(verify, "distance")
            total_time = self._var_value(verify, "time")
        elif scenario == "work_problem":
            total_distance = self._var_value(verify, "total_days")
            total_time = total_distance or 0.0
        elif scenario == "average_problem":
            total_distance = self._var_value(verify, "average")
            total_time = total_distance or 0.0
        elif scenario == "overlap_splice":
            total_distance = self._var_value(verify, "total_length")
            total_time = self._var_value(verify, "overlap") or 0.0
        elif scenario == "round_trip":
            total_distance = self._var_value(verify, "total_distance")
            total_time = self._var_value(verify, "trips") or 0.0
        elif scenario == "sum_multiple":
            total_distance = self._var_value(verify, "big")
            total_time = self._var_value(verify, "small") or 0.0
        elif scenario == "sprinkler_area":
            total_distance = self._var_value(verify, "area")
            total_time = self._var_value(verify, "length") or 0.0
        elif scenario == "tree_planting":
            total_distance = self._var_value(verify, "trees")
            total_time = self._var_value(verify, "segments") or 0.0
        elif scenario == "displacement_volume":
            total_distance = self._var_value(verify, "volume")
            total_time = self._var_value(verify, "rise") or 0.0
        elif scenario == "profit_loss":
            total_distance = self._var_value(verify, "people")
            total_time = total_distance or 0.0
        elif scenario == "simple_interest":
            total_distance = self._var_value(verify, "interest")
            total_time = self._var_value(verify, "total") or 0.0
        elif scenario == "tiered_pricing":
            total_distance = self._var_value(verify, "total_price")
            total_time = self._var_value(verify, "extra_distance") or 0.0
        elif scenario == "weekday_calc":
            total_distance = self._var_value(verify, "target_day")
            total_time = self._var_value(verify, "add_days") or 0.0
        elif scenario == "semicircle_perimeter":
            total_distance = self._var_value(verify, "perimeter")
            total_time = self._var_value(verify, "arc") or 0.0
        elif scenario == "cuboid_combine_surface":
            total_distance = self._var_value(verify, "max_sa")
            total_time = self._var_value(verify, "min_sa") or 0.0
        elif scenario == "combination_count":
            total_distance = self._var_value(verify, "combinations")
            total_time = total_distance or 0.0
        elif scenario == "unitary_combined":
            total_distance = self._var_value(verify, "result")
            total_time = self._var_value(verify, "unit_rate") or 0.0
        elif scenario == "redundant_filter":
            total_distance = self._var_value(verify, "remaining")
            total_time = self._var_value(verify, "removed") or 0.0
        elif scenario == "fold_cut":
            total_distance = self._var_value(verify, "segments")
            total_time = self._var_value(verify, "folds") or 0.0
        elif scenario == "stars_bars":
            total_distance = self._var_value(verify, "ways")
            total_time = self._var_value(verify, "n_bins") or 0.0

        dsl = SceneDSL(
            subject="math",
            template_type=scenario,
            meta={"title": problem[:60], "original_text": problem, "knowledge_node_id": knowledge_node_id},
            entities=[e.to_dict() for e in entities_list],
            canvas_config={
                "dimension": "2D",
                "scale_mapping": {"unit_to_pixel_ratio": self._calc_scale(total_distance), "auto_fit": True},
            },
            timeline={
                "total_distance": total_distance or 0.0,
                "total_time": total_time or 0.0,
                "milestones": [m.to_dict() for m in milestones],
            },
            pedagogy={
                "misconception_breakdown": str(extracted.get("misconception_hint", ""))[:200],
                "key_takeaway": "",
                "prerequisite_node_ids": [],
            },
            verified=bool(verify and verify.verified),
            error=verify.error if verify else ("未知场景, 降级静态推导" if scenario == "unknown" else ""),
            fallback=bool(verify and verify.fallback) or scenario not in _KNOWN_SCENARIOS,
        )
        # 通用路径 (issue: 新题型全部降级) — 模板未命中/校验失败/无答案时, S1 开放提取
        # → S2 SymPy 解方程 → S3 可视化原语, 仅当提取失败或不可解才真正降级。
        # 模板 verify "通过"但 total_distance/total_time 均空 (如 queue_counting 映射缺失)
        # 同样视为模板未产出答案, 回退通用管线兜底。
        template_no_answer = not (total_distance or total_time)
        if dsl.fallback or template_no_answer:
            generic = await self._compile_generic(problem, knowledge_node_id)
            if generic is not None:
                return generic
        logger.info("scene_compiler: scenario=%s verified=%s fallback=%s", scenario, dsl.verified, dsl.fallback)
        return dsl

    async def _compile_generic(self, problem: str, knowledge_node_id: str) -> SceneDSL | None:
        """通用路径 — 任意新题型: 开放提取 → SymPy 求解 → 可视化原语 DSL。

        返回 None 表示通用路径也失败 (提取不可用/方程不可解), 调用方维持降级。
        """
        prompt = generic_pipeline.build_generic_prompt(problem)
        try:
            raw = await self.mlx.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1024)
        except Exception as exc:
            logger.warning("scene_compiler: 通用路径提取失败 %s", exc)
            return None
        parsed = generic_pipeline.parse_generic_extraction(raw)
        if parsed is None:
            logger.info("scene_compiler: 通用路径提取结构不合规, 维持降级")
            return None
        solution = generic_pipeline.solve_generic(parsed)
        if solution is None:
            logger.info("scene_compiler: 通用路径方程不可解, 维持降级")
            return None
        answer = solution.get("__answer__", 0.0)
        # 分步推导 pipeline (Gemini 方案融合): 受限 AST 求值, 终值与 SymPy 答案交叉验证 —
        # 一致才采用分步渲染 (双引擎互证), 不一致/执行失败退回 SymPy 直答。
        pipeline_eval = generic_pipeline.eval_pipeline(parsed)
        pipeline_ok = (
            pipeline_eval is not None
            and abs(pipeline_eval["final"] - answer) <= max(1e-6, abs(answer) * 1e-6)
        )
        if pipeline_eval is not None and not pipeline_ok:
            logger.info("scene_compiler: pipeline 终值 %s 与 SymPy %s 不一致, 弃用分步", pipeline_eval["final"], answer)
        visual = parsed["visual"]
        entities: list[SceneEntity] = []
        for name, val in parsed["knowns"].items():
            entities.append(SceneEntity(id=name, type="reference_line", label=name,
                                        value=float(val), unit=parsed["units"].get(name, "")))
        for name, val in solution.items():
            if name == "__answer__":
                continue
            entities.append(SceneEntity(id=name, type="moving_object", label=name, value=float(val)))
        # 里程碑: 有分步 pipeline 时按步骤均分进度段; 否则退回三阶段占位
        if pipeline_ok:
            milestones = []
            n = len(pipeline_eval["steps"])
            for i, s in enumerate(pipeline_eval["steps"]):
                milestones.append(Milestone(
                    progress_percentage=round(i / n * 100, 1), time_mark=i / n,
                    event_name=s["title"], highlight_entities=[],
                    formula_state=f"{s['formula']} → {s['value']:g}{s['result_unit']}",
                ))
            milestones.append(Milestone(
                progress_percentage=100.0, time_mark=1.0, event_name="验算通过",
                highlight_entities=[], formula_state=f"{parsed['answer_expr']} = {answer:g}{answer_unit}" if (answer_unit := parsed["answer_unit"]) else f"{parsed['answer_expr']} = {answer:g}",
            ))
        else:
            milestones = [
                Milestone(progress_percentage=0.0, time_mark=0.0, event_name="提取已知量",
                          highlight_entities=[e.id for e in entities[:3]],
                          formula_state=", ".join(parsed["equations"])[:120]),
                Milestone(progress_percentage=50.0, time_mark=0.5, event_name="解方程",
                          highlight_entities=[], formula_state=parsed["answer_expr"]),
                Milestone(progress_percentage=100.0, time_mark=1.0, event_name="求解完成",
                          highlight_entities=[], formula_state=f"{parsed['answer_expr']} = {answer:g}"),
            ]
        answer_unit = parsed["answer_unit"]
        dsl = SceneDSL(
            subject="math",
            template_type="generic_solve",
            meta={
                "title": problem[:60], "original_text": problem,
                "knowledge_node_id": knowledge_node_id,
                "pipeline": "generic",  # 前端据此走通用渲染器
            },
            entities=[e.to_dict() for e in entities],
            canvas_config={
                "dimension": "2D",
                "visual": visual,
                # 分步推导 (Gemini 方案融合): pipeline_ok 时前端按步骤分段高亮
                "pipeline": pipeline_eval["steps"] if pipeline_ok else [],
                "parameters": [{"key": k, "label": k, "value": v, "unit": parsed["units"].get(k, "")}
                               for k, v in parsed["knowns"].items()],
                "scale_mapping": {"unit_to_pixel_ratio": self._calc_scale(abs(answer) or 1.0), "auto_fit": True},
            },
            timeline={
                "total_distance": abs(answer) or 1.0,
                "total_time": 1.0,
                "answer": answer,
                "answer_unit": answer_unit,
                "milestones": [m.to_dict() for m in milestones],
            },
            pedagogy={
                "misconception_breakdown": parsed["misconception_hint"],
                "key_takeaway": parsed["steps"][-1] if parsed["steps"] else "",
                "prerequisite_node_ids": [],
                "steps": parsed["steps"],
                "question_focus": parsed["question_focus"],
            },
            verified=True,
            error="",
            fallback=False,
        )
        logger.info("scene_compiler: generic_solve verified answer=%g visual=%s", answer, visual.get("kind"))
        return dsl

    @staticmethod
    def _var_value(verify: VerifyResult | None, name: str) -> float | None:
        if not verify:
            return None
        v = verify.variables.get(name)
        if not v:
            return None
        try:
            return float(v.get("value", 0))
        except (TypeError, ValueError):
            return None

    def _flatten_entities(self, scenario: str, entities: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, val in entities.items():
            if not isinstance(val, dict):
                continue
            label = key.lower()
            if "total" in val and "removed" in val:
                out["total"] = float(val["total"])
                out["removed"] = float(val["removed"])
                if "distraction" in val:
                    out["distraction"] = float(val["distraction"])
            elif "folds" in val:
                out["folds"] = float(val["folds"])
            elif "n_bins" in val and "n_items" in val:
                out["n_items"] = float(val["n_items"])
                out["n_bins"] = float(val["n_bins"])
                if "min_per" in val:
                    out["min_per"] = float(val["min_per"])
            elif "n_segments" in val or "time_per_cut" in val:
                if "n_segments" in val:
                    out["n_segments"] = float(val["n_segments"])
                if "time_per_cut" in val:
                    out["time_per_cut"] = float(val["time_per_cut"])
            elif "rank_front" in val or "rank_behind" in val:
                if "rank_front" in val:
                    out["rank_front"] = float(val["rank_front"])
                if "rank_behind" in val:
                    out["rank_behind"] = float(val["rank_behind"])
            elif "heads" in val and "legs" in val:
                out["heads"] = float(val["heads"])
                out["legs"] = float(val["legs"])
            elif "n_items" in val or "total_value" in val or "n_target" in val:
                if "n_items" in val:
                    out["n_items"] = float(val["n_items"])
                if "total_value" in val:
                    out["total_value"] = float(val["total_value"])
                if "n_target" in val:
                    out["n_target"] = float(val["n_target"])
            elif "total_sum" in val or "count" in val:
                if "total_sum" in val:
                    out["total_sum"] = float(val["total_sum"])
                if "count" in val:
                    out["count"] = float(val["count"])
            elif "board1" in val or "board2" in val or "overlap" in val:
                if "board1" in val:
                    out["board1"] = float(val["board1"])
                if "board2" in val:
                    out["board2"] = float(val["board2"])
                if "overlap" in val:
                    out["overlap"] = float(val["overlap"])
            elif "trips" in val and "distance" in val:
                out["distance"] = float(val["distance"])
                out["trips"] = float(val["trips"])
            elif "sum" in val and "multiple" in val:
                out["sum"] = float(val["sum"])
                out["multiple"] = float(val["multiple"])
            elif "sprinkler" in label or ("width" in val and "time" in val and "speed" in val):
                if "speed" in val:
                    out["speed"] = float(val["speed"])
                if "width" in val:
                    out["width"] = float(val["width"])
                if "time" in val:
                    out["time"] = float(val["time"])
            elif "spacing" in val and "length" in val:
                out["length"] = float(val["length"])
                out["spacing"] = float(val["spacing"])
                if "mode_code" in val:
                    out["mode_code"] = float(val["mode_code"])
            elif "rise" in val and ("length" in val or "width" in val):
                if "length" in val:
                    out["length"] = float(val["length"])
                if "width" in val:
                    out["width"] = float(val["width"])
                if "rise" in val:
                    out["rise"] = float(val["rise"])
            elif "surplus" in val or "deficit" in val or "diff" in val:
                if "surplus" in val:
                    out["surplus"] = float(val["surplus"])
                if "deficit" in val:
                    out["deficit"] = float(val["deficit"])
                if "diff" in val:
                    out["diff"] = float(val["diff"])
            elif "principal" in val and "rate" in val:
                if "principal" in val:
                    out["principal"] = float(val["principal"])
                rate_val = float(val["rate"])
                if rate_val > 1.0:
                    rate_val = rate_val / 100.0
                out["rate"] = rate_val
                if "years" in val:
                    out["years"] = float(val["years"])
            elif "base_distance" in val or "base_price" in val:
                if "base_distance" in val:
                    out["base_distance"] = float(val["base_distance"])
                if "base_price" in val:
                    out["base_price"] = float(val["base_price"])
                if "unit_price" in val:
                    out["unit_price"] = float(val["unit_price"])
                if "total_distance" in val:
                    out["total_distance"] = float(val["total_distance"])
            elif "start_day" in val and "add_days" in val:
                out["start_day"] = float(val["start_day"])
                out["add_days"] = float(val["add_days"])
            elif "radius" in val:
                out["radius"] = float(val["radius"])
            elif "length" in val and "width" in val and "height" in val:
                out["length"] = float(val["length"])
                out["width"] = float(val["width"])
                out["height"] = float(val["height"])
            elif "n_items1" in val or "n_items2" in val:
                if "n_items1" in val:
                    out["n_items1"] = float(val["n_items1"])
                if "n_items2" in val:
                    out["n_items2"] = float(val["n_items2"])
            elif "n_people" in val and "total_work" in val:
                if "n_people" in val:
                    out["n_people"] = float(val["n_people"])
                if "n_days" in val:
                    out["n_days"] = float(val["n_days"])
                if "total_work" in val:
                    out["total_work"] = float(val["total_work"])
                if "target_people" in val:
                    out["target_people"] = float(val["target_people"])
                if "target_days" in val:
                    out["target_days"] = float(val["target_days"])
            elif "worker1" in label or (label == "worker1"):
                if "days" in val:
                    out["worker1_days"] = float(val["days"])
            elif "worker2" in label:
                if "days" in val:
                    out["worker2_days"] = float(val["days"])
            elif "fence" in label or "篱笆" in str(val.get("label", "")):
                if "length" in val:
                    out["length"] = float(val["length"])
                if "perimeter" in val:
                    out["perimeter"] = float(val["perimeter"])
            elif "traveler" in label or "行人" in str(val.get("label", "")):
                if "distance" in val:
                    out["distance"] = float(val["distance"])
                if "speed" in val:
                    out["speed"] = float(val["speed"])
                if "time" in val:
                    out["time"] = float(val["time"])
            elif "bridge" in label or "桥" in str(val.get("label", "")):
                if "length" in val:
                    out["L_bridge"] = float(val["length"])
            elif "train" in label or "车" in str(val.get("label", "")):
                if "length" in val:
                    out["L_train"] = float(val["length"])
                if "speed" in val:
                    out["v_train"] = float(val["speed"])
            elif "pedestrian" in label or "person" in label or "人" in str(val.get("label", "")):
                if "speed" in val:
                    out["v_pedestrian"] = float(val["speed"])
            elif label in ("train1", "t1", "甲"):
                out["L1"] = float(val.get("length", 0))
                out["v1"] = float(val.get("speed", 0))
            elif label in ("train2", "t2", "乙"):
                out["L2"] = float(val.get("length", 0))
                out["v2"] = float(val.get("speed", 0))
        if scenario == "echo_problem":
            out.setdefault("v_sound", 340.0)
            out.setdefault("t_echo", 2.0)
        return out

    def _build_entities_list(self, entities_raw: dict[str, Any], verify: VerifyResult | None) -> list[SceneEntity]:
        out: list[SceneEntity] = []
        for key, val in entities_raw.items():
            if not isinstance(val, dict):
                continue
            label = str(val.get("label", key))
            if "total" in val and "removed" in val:
                out.append(SceneEntity(id="total", type="static_structure", label="原有", value=float(val["total"]), unit="只"))
                out.append(SceneEntity(id="removed", type="moving_object", label="飞走", value=float(val["removed"]), unit="只"))
                if "distraction" in val:
                    out.append(SceneEntity(id="distraction", type="reference_line", label="干扰(不参与)", value=float(val["distraction"]), unit=""))
                continue
            if "folds" in val:
                out.append(SceneEntity(id="folds", type="static_structure", label="对折次数", value=float(val["folds"]), unit="次"))
                continue
            if "n_bins" in val and "n_items" in val:
                out.append(SceneEntity(id="n_items", type="static_structure", label="物品数", value=float(val["n_items"]), unit="个"))
                out.append(SceneEntity(id="n_bins", type="static_structure", label="容器数", value=float(val["n_bins"]), unit="个"))
                if "min_per" in val:
                    out.append(SceneEntity(id="min_per", type="static_structure", label="每容器最少", value=float(val["min_per"]), unit="个"))
                continue
            if "n_segments" in val or "time_per_cut" in val:
                if "n_segments" in val:
                    out.append(SceneEntity(id="n_segments", type="static_structure", label="段数", value=float(val["n_segments"]), unit="段"))
                if "time_per_cut" in val:
                    out.append(SceneEntity(id="time_per_cut", type="static_structure", label="每次耗时", value=float(val["time_per_cut"]), unit="分"))
                continue
            if "rank_front" in val or "rank_behind" in val:
                if "rank_front" in val:
                    out.append(SceneEntity(id="rank_front", type="moving_object", label="从前位次", value=float(val["rank_front"]), unit="位"))
                if "rank_behind" in val:
                    out.append(SceneEntity(id="rank_behind", type="moving_object", label="从后位次", value=float(val["rank_behind"]), unit="位"))
                continue
            if "heads" in val and "legs" in val:
                out.append(SceneEntity(id="heads", type="static_structure", label="头数", value=float(val["heads"]), unit="头"))
                out.append(SceneEntity(id="legs", type="static_structure", label="腿数", value=float(val["legs"]), unit="腿"))
                continue
            if "n_items" in val or "total_value" in val or "n_target" in val:
                if "n_items" in val:
                    out.append(SceneEntity(id="n_items", type="static_structure", label="件数", value=float(val["n_items"]), unit="件"))
                if "total_value" in val:
                    out.append(SceneEntity(id="total_value", type="static_structure", label="总价", value=float(val["total_value"]), unit="元"))
                if "n_target" in val:
                    out.append(SceneEntity(id="n_target", type="static_structure", label="目标件数", value=float(val["n_target"]), unit="件"))
                continue
            if "total_sum" in val or "count" in val:
                if "total_sum" in val:
                    out.append(SceneEntity(id="total_sum", type="static_structure", label="总和", value=float(val["total_sum"]), unit=""))
                if "count" in val:
                    out.append(SceneEntity(id="count", type="static_structure", label="个数", value=float(val["count"]), unit="个"))
                continue
            if "board1" in val or "board2" in val or "overlap" in val:
                if "board1" in val:
                    out.append(SceneEntity(id="board1", type="static_structure", label="板1长", value=float(val["board1"]), unit="cm"))
                if "board2" in val:
                    out.append(SceneEntity(id="board2", type="static_structure", label="板2长", value=float(val["board2"]), unit="cm"))
                if "overlap" in val:
                    out.append(SceneEntity(id="overlap", type="reference_line", label="重叠", value=float(val["overlap"]), unit="cm"))
                continue
            if "trips" in val and "distance" in val:
                out.append(SceneEntity(id="distance", type="moving_object", label="单程", value=float(val["distance"]), unit="m"))
                out.append(SceneEntity(id="trips", type="static_structure", label="往返次数", value=float(val["trips"]), unit="次"))
                continue
            if "sum" in val and "multiple" in val:
                out.append(SceneEntity(id="sum", type="static_structure", label="和", value=float(val["sum"]), unit=""))
                out.append(SceneEntity(id="multiple", type="static_structure", label="倍数", value=float(val["multiple"]), unit="倍"))
                continue
            if "spacing" in val and "length" in val:
                out.append(SceneEntity(id="length", type="static_structure", label="路长", value=float(val["length"]), unit="m"))
                out.append(SceneEntity(id="spacing", type="static_structure", label="间距", value=float(val["spacing"]), unit="m"))
                if "mode_code" in val:
                    out.append(SceneEntity(id="mode_code", type="reference_line", label="模式", value=float(val["mode_code"]), unit=""))
                continue
            if "rise" in val and ("length" in val or "width" in val):
                if "length" in val:
                    out.append(SceneEntity(id="length", type="static_structure", label="水箱长", value=float(val["length"]), unit="cm"))
                if "width" in val:
                    out.append(SceneEntity(id="width", type="static_structure", label="水箱宽", value=float(val["width"]), unit="cm"))
                out.append(SceneEntity(id="rise", type="reference_line", label="上升高", value=float(val["rise"]), unit="cm"))
                continue
            if "surplus" in val or "deficit" in val or "diff" in val:
                if "surplus" in val:
                    out.append(SceneEntity(id="surplus", type="static_structure", label="盈", value=float(val["surplus"]), unit="支"))
                if "deficit" in val:
                    out.append(SceneEntity(id="deficit", type="static_structure", label="亏", value=float(val["deficit"]), unit="支"))
                if "diff" in val:
                    out.append(SceneEntity(id="diff", type="reference_line", label="分配差", value=float(val["diff"]), unit="支"))
                continue
            if "principal" in val and "rate" in val:
                rate_val = float(val["rate"])
                if rate_val > 1.0:
                    rate_val = rate_val / 100.0
                out.append(SceneEntity(id="principal", type="static_structure", label="本金", value=float(val["principal"]), unit="元"))
                out.append(SceneEntity(id="rate", type="reference_line", label="年利率", value=rate_val, unit=""))
                if "years" in val:
                    out.append(SceneEntity(id="years", type="moving_object", label="年数", value=float(val["years"]), unit="年"))
                continue
            if "base_distance" in val or "base_price" in val:
                if "base_distance" in val:
                    out.append(SceneEntity(id="base_distance", type="static_structure", label="起步距离", value=float(val["base_distance"]), unit="km"))
                if "base_price" in val:
                    out.append(SceneEntity(id="base_price", type="static_structure", label="起步价", value=float(val["base_price"]), unit="元"))
                if "unit_price" in val:
                    out.append(SceneEntity(id="unit_price", type="reference_line", label="超出单价", value=float(val["unit_price"]), unit="元/km"))
                if "total_distance" in val:
                    out.append(SceneEntity(id="total_distance", type="moving_object", label="总距离", value=float(val["total_distance"]), unit="km"))
                continue
            if "start_day" in val and "add_days" in val:
                out.append(SceneEntity(id="start_day", type="static_structure", label="今天星期", value=float(val["start_day"]), unit=""))
                out.append(SceneEntity(id="add_days", type="moving_object", label="过几天", value=float(val["add_days"]), unit="天"))
                continue
            if "radius" in val:
                out.append(SceneEntity(id="radius", type="static_structure", label="半径", value=float(val["radius"]), unit="cm"))
                continue
            if "length" in val and "width" in val and "height" in val:
                out.append(SceneEntity(id="length", type="static_structure", label="长", value=float(val["length"]), unit="cm"))
                out.append(SceneEntity(id="width", type="static_structure", label="宽", value=float(val["width"]), unit="cm"))
                out.append(SceneEntity(id="height", type="static_structure", label="高", value=float(val["height"]), unit="cm"))
                continue
            if "n_items1" in val or "n_items2" in val:
                if "n_items1" in val:
                    out.append(SceneEntity(id="n_items1", type="static_structure", label="上衣", value=float(val["n_items1"]), unit="件"))
                if "n_items2" in val:
                    out.append(SceneEntity(id="n_items2", type="static_structure", label="裤子", value=float(val["n_items2"]), unit="条"))
                continue
            if "n_people" in val and "total_work" in val:
                if "n_people" in val:
                    out.append(SceneEntity(id="n_people", type="static_structure", label="人数", value=float(val["n_people"]), unit="人"))
                if "n_days" in val:
                    out.append(SceneEntity(id="n_days", type="static_structure", label="天数", value=float(val["n_days"]), unit="天"))
                if "total_work" in val:
                    out.append(SceneEntity(id="total_work", type="static_structure", label="总量", value=float(val["total_work"]), unit="个"))
                if "target_people" in val:
                    out.append(SceneEntity(id="target_people", type="moving_object", label="目标人数", value=float(val["target_people"]), unit="人"))
                if "target_days" in val:
                    out.append(SceneEntity(id="target_days", type="moving_object", label="目标天数", value=float(val["target_days"]), unit="天"))
                continue
            if "speed" in val and "width" in val and "time" in val:
                out.append(SceneEntity(id="speed", type="moving_object", label="速度", value=float(val["speed"]), unit="m/分"))
                out.append(SceneEntity(id="width", type="static_structure", label="宽", value=float(val["width"]), unit="m"))
                out.append(SceneEntity(id="time", type="moving_object", label="时间", value=float(val["time"]), unit="分"))
                continue
            if "days" in val:
                out.append(SceneEntity(id=str(key) + "_days", type="moving_object", label=label, value=float(val["days"]), unit="天"))
                continue
            if "perimeter" in val:
                if "length" in val:
                    out.append(SceneEntity(id="length", type="static_structure", label="靠墙长", value=float(val["length"]), unit="m"))
                out.append(SceneEntity(id="perimeter", type="static_structure", label="三边周长", value=float(val["perimeter"]), unit="m"))
                continue
            if "distance" in val or ("speed" in val and "time" in val):
                if "distance" in val:
                    out.append(SceneEntity(id="distance", type="moving_object", label="路程", value=float(val["distance"]), unit="m"))
                if "speed" in val:
                    out.append(SceneEntity(id="speed", type="moving_object", label="速度", value=float(val["speed"]), unit="m/s"))
                if "time" in val:
                    out.append(SceneEntity(id="time", type="moving_object", label="时间", value=float(val["time"]), unit="s"))
                continue
            if "bridge" in key.lower() or "桥" in label or "train" in key.lower() or "车" in label or "pedestrian" in key.lower() or "人" in label or key.lower() in ("train1", "t1", "甲", "train2", "t2", "乙"):
                out.append(SceneEntity(
                    id=str(key),
                    type="static_structure" if ("bridge" in key.lower() or "桥" in label) else "moving_object",
                    label=label,
                    value=float(val.get("length", val.get("speed", 0)) or 0),
                    unit="m" if "length" in val else "m/s",
                ))
                continue
            out.append(SceneEntity(
                id=str(key),
                type="static_structure" if ("bridge" in key or "桥" in str(val.get("label", ""))) else "moving_object",
                label=label,
                value=float(val.get("length", val.get("speed", 0)) or 0),
                unit="m" if "length" in val else "m/s",
            ))
        if verify:
            unit_map = {"total_people": "人", "area": "m²", "width": "m", "unit_value": "元", "target_value": "元",
                        "rabbit": "只", "chicken": "只", "total_days": "天", "average": "", "rate1": "", "rate2": "",
                        "total_length": "cm", "total_distance": "m", "small": "", "big": "", "length": "m",
                        "segments": "段", "trees": "棵", "volume": "cm³", "people": "人",
                        "interest": "元", "total": "元",
                        "total_price": "元", "extra_distance": "km", "target_day": "",
                        "arc": "cm", "diameter": "cm", "perimeter": "cm",
                        "min_face": "cm²", "max_face": "cm²", "single_sa": "cm²",
                        "max_sa": "cm²", "min_sa": "cm²",
                        "combinations": "种", "unit_rate": "", "result": "个",
                        "remaining": "只", "ways": "种"}
            for vname, vdata in verify.variables.items():
                if vname in UNKNOWN_VARS:
                    out.append(SceneEntity(id=vname, type="reference_line", label=str(vdata.get("label", vname)), value=float(vdata.get("value", 0)), unit=unit_map.get(vname, "m")))
        return out[:20]

    def _build_milestones(self, raw_milestones: list, verify: VerifyResult | None, scenario: str = "") -> list[Milestone]:
        if not isinstance(raw_milestones, list):
            raw_milestones = []
        # cutting 场景: LLM 不懂切割点分布, 强制用 SymPy 离散生成
        if scenario == "cutting_segments" and verify:
            n_cuts = int(self._var_value(verify, "n_cuts") or 0)
            total = self._var_value(verify, "total_time") or 0.0
            if n_cuts > 0:
                out: list[Milestone] = []
                for i in range(n_cuts + 1):
                    ratio = i / n_cuts
                    out.append(Milestone(
                        ratio * 100.0,
                        total * ratio,
                        "起点" if i == 0 else f"第{i}次锯切完成",
                        [],
                    ))
                return out
            return [Milestone(0.0, 0.0, "无需锯切", [])]
        if scenario in ("queue_counting", "chicken_rabbit", "work_problem",
                         "average_problem", "fence_against_wall", "unitary_method",
                         "overlap_splice", "round_trip", "sum_multiple",
                         "sprinkler_area", "tree_planting",
                         "displacement_volume", "profit_loss",
                         "simple_interest", "tiered_pricing", "weekday_calc",
                         "semicircle_perimeter", "cuboid_combine_surface",
                         "combination_count", "unitary_combined",
                         "redundant_filter", "fold_cut", "stars_bars") and verify:
            total = (self._var_value(verify, "total_people")
                     or self._var_value(verify, "total_days")
                     or self._var_value(verify, "average")
                     or self._var_value(verify, "area")
                     or self._var_value(verify, "target_value")
                     or self._var_value(verify, "total_length")
                     or self._var_value(verify, "total_distance")
                     or self._var_value(verify, "big")
                     or self._var_value(verify, "trees")
                     or self._var_value(verify, "volume")
                     or self._var_value(verify, "people")
                     or self._var_value(verify, "interest")
                     or self._var_value(verify, "total_price")
                     or self._var_value(verify, "target_day")
                     or self._var_value(verify, "perimeter")
                     or self._var_value(verify, "max_sa")
                     or self._var_value(verify, "combinations")
                     or self._var_value(verify, "result")
                     or self._var_value(verify, "remaining")
                     or self._var_value(verify, "segments")
                     or self._var_value(verify, "ways")
                     or 0.0)
            out = [
                Milestone(0.0, 0.0, "起点", []),
                Milestone(50.0, total * 0.5, "半程", []),
                Milestone(100.0, total, "完成", []),
            ]
            return out
        out = []
        for ms in raw_milestones[:10]:
            if not isinstance(ms, dict):
                continue
            ratio = float(ms.get("time_ratio", ms.get("progress_percentage", 0)) or 0)
            out.append(Milestone(
                progress_percentage=ratio * 100 if ratio <= 1.0 else ratio,
                time_mark=(self._var_value(verify, "t") or 0) * ratio,
                event_name=str(ms.get("event", ms.get("label", "")))[:40],
                highlight_entities=[str(h) for h in ms.get("highlight_entities", [])][:5],
                formula_state=str(ms.get("formula_state", ""))[:100],
            ))
        if not out and verify:
            t = self._var_value(verify, "t") or 0.0
            out = [
                Milestone(0.0, 0.0, "start", ["train_head"]),
                Milestone(50.0, t * 0.5, "mid", ["train_body"]),
                Milestone(100.0, t, "end", ["train_tail"]),
            ]
        return out

    @staticmethod
    def _calc_scale(total_distance: float | None) -> float:
        if not total_distance or total_distance <= 0:
            return 1.0
        return 720.0 / total_distance
