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
10. 拼接/组合几何题: 先判定拼接方向与重合边, 再推新图形边长 — 如两个 a×b 长方形
   拼成正方形, 沿长边接缝则新边长 = b (须满足 2b = a), 沿短边接则边长 = a+b;
   用已知量验证哪个方向能得到题目所说的形状, 选对的那条边长算周长/面积。
11. equations 的解必须直接就是题目所问的量 (与 question_focus 一致) —
   题目问"削去/剩余/相差多少"时, 方程要表达该差值本身,
   不要把中间量 (如整体的一部分) 当答案; 可用括号式表达
   (如削去体积 = 底面积*高*(1 - 1/3))。
13. 年龄问题: 二人年龄差恒不变 — "几年前/几年后 x 年父龄是子龄的 k 倍"
   列 (father_age - x) - k*(child_age - x); 若解出 x=0 说明恰好今年成立,
   "几年前"的答案就是 0 (不要硬凑非零解)。
14. 余数同余题 (除以a余r, 除以b余r, ...): 余数相同时被除数 = lcm(a,b,...) * k + r,
   求"最小正数"取 k=1 (k=0 给出余数本身 r, 若 r>0 且题目要求更大的数则 k=1);
   用方程 n - (a*b/gcd)*(k) - r 形式列, 或直接验证最小候选。
12. pipeline: 分步推导链 (2-5 步), 每步:
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

参考范例 (同构题型 — 注意方程的解必须直接就是所问的量):

范例1 (削去/剩余类 — 问的是"削去"不是"保留"):
{"knowns": {"base_area": {"value": 10, "unit": "cm²"}, "height": {"value": 6, "unit": "cm"}}, "unknowns": ["target"], "equations": ["target - base_area*height*(1 - 1/3)"], "answer_expr": "target", "answer_unit": "立方厘米", "steps": ["柱体积=10*6=60", "削去=柱×2/3=40"], "pipeline": [{"step":1,"title":"柱体积","formula":"V=10*6=60","eval":"params.base_area*params.height","result_unit":"立方厘米"},{"step":2,"title":"削去体积","formula":"V*2/3=40","eval":"results[1]*2/3","result_unit":"立方厘米"}]}
关键: "削去" = 整体 × (1 - 1/3) = 整体 × 2/3, 不是保留部分本身。

范例2 (拼接类 — 先验证形状约束再定新边长):
{"knowns": {"rect_length": {"value": 10, "unit": "cm"}, "rect_width": {"value": 5, "unit": "cm"}}, "unknowns": ["target"], "equations": ["target - 4*rect_length"], "answer_expr": "target", "answer_unit": "厘米", "steps": ["验证: 沿长边拼接 → 新边 = 宽*2 = 10 = 原 长, 是正方形", "周长 = 4*10 = 40"], "pipeline": [{"step":1,"title":"验证并定新边长","formula":"2*宽=10=长 → 新边长=长=10","eval":"params.rect_length","result_unit":"厘米"},{"step":2,"title":"周长","formula":"4*10=40","eval":"results[1]*4","result_unit":"厘米"}]}
关键: 用数值验证哪个拼接方向能形成目标形状 (宽*2 == 长 成立 → 新边长=长), 再算。

范例3 (判断型题 — 能不能/对不对/够不够, 无需求未知数):
题: 用长 3cm、4cm 和 8cm 的三根小棒, 能拼成一个三角形吗?
{"question_kind": "judgment", "knowns": {"side1": {"value": 3, "unit": "cm"}, "side2": {"value": 4, "unit": "cm"}, "side3": {"value": 8, "unit": "cm"}}, "criterion": {"expr": "side1 + side2 - side3", "true_meaning": "两边之和大于第三边, 能拼成三角形", "false_meaning": "两边之和小于等于第三边, 三线段重合, 不能拼成三角形"}, "steps": ["三角形需任意两边之和大于第三边", "最短两边之和 3+4=7 < 8", "结论: 不能"], "visual": {"kind": "bar_model"}, "misconception_hint": "只验证一对边之和大于第三边不够, 须最短两边之和大于最长边"}
关键: 判断题不设 unknowns/equations/pipeline, criterion.expr 用已知量算出数值 —
结果 >0 取 true_meaning, =0 或 <0 取 false_meaning。

范例4 (余数/同余类 — 除以a余r, 除以b余r, 余数相同, 求最小正数):
题: 一个数除以2余1，除以3余1，除以5余1，这个数最小是多少？
关键推导: 余数相同 (都是1) → 这个数减去1后能同时被 2、3、5 整除 → 减去余数后是公倍数 → 最小就是最小公倍数 lcm(2,3,5)。逐个验证: 30/2=15 ✓ 30/3=10 ✓ 30/5=6 ✓ → lcm=30 → 所求数 = 30+1 = 31。
{"question_kind": "solve", "knowns": {"divisor_product": {"value": 30, "unit": ""}, "remainder": {"value": 1, "unit": ""}}, "unknowns": ["target"], "equations": ["target - divisor_product - remainder"], "answer_expr": "target", "answer_unit": "", "steps": ["余数相同(1) → 数-1 是 2,3,5 的公倍数", "最小公倍数逐个验证: 30/2=15✓ 30/3=10✓ 30/5=6✓ → lcm=30", "所求数 = 30+1 = 31"], "pipeline": [{"step":1,"title":"求最小公倍数并逐个验证","formula":"30/2=15✓ 30/3=10✓ 30/5=6✓ → lcm=30","eval":"params.divisor_product","result_unit":""},{"step":2,"title":"加余数","formula":"30+1=31","eval":"results[1] + params.remainder","result_unit":""}], "visual": {"kind": "flow"}, "question_focus": "最小正数", "misconception_hint": "divisor_product 必须逐个验证能被每个除数整除且最小 — 是 lcm 而非随便的公倍数; 两两互质的除数 lcm=连乘 (如 2*3*5=30, 3*5*7=105), 不要多乘任何因子"}
关键: divisor_product 必须填**最小公倍数**, 填完逐个验证能被每个除数整除;
   两两互质的除数 lcm = 连乘 (如 2*3*5=30, 3*5*7=105), 不要多乘任何因子;
   方程 target - divisor_product - remainder。

范例5 (间隔类 — 敲钟/锯木/爬楼: 次数与间隔数差 1):
题: 钟敲6下用了10秒，敲12下要用多少秒？
关键推导: 敲6下有 6-1=5 个间隔, 每个间隔 10/5=2 秒; 敲12下有 11 个间隔 → 11*2=22 秒。
{"knowns": {"first_times": {"value": 6, "unit": "下"}, "first_seconds": {"value": 10, "unit": "秒"}, "target_times": {"value": 12, "unit": "下"}}, "unknowns": ["target"], "equations": ["target - (target_times - 1) * (first_seconds / (first_times - 1))"], "answer_expr": "target", "answer_unit": "秒", "steps": ["敲6下 → 5个间隔, 每间隔 10/5=2秒", "敲12下 → 11个间隔", "11*2=22秒"], "pipeline": [{"step":1,"title":"求每个间隔时长","formula":"10/(6-1)=2秒","eval":"params.first_seconds / (params.first_times - 1)","result_unit":"秒"},{"step":2,"title":"求敲12下总时长","formula":"(12-1)*2=22秒","eval":"results[1] * (params.target_times - 1)","result_unit":"秒"}], "visual": {"kind": "timeline"}, "question_focus": "总时长", "misconception_hint": "次数与间隔数差 1: 间隔数=次数-1, 直接用次数乘会多算一个间隔"}
关键: 锯木(段数-1=锯次)、爬楼(楼层-1=层数)、敲钟(下数-1=间隔) 同构 —
   都用 (次数-1) 作为间隔数, 不要直接乘次数。

范例6 (还原倒推类 — 从结果往回推, 逆运算逐层还原):
题: 一个数加上10再乘2，再减去8得20，这个数是多少？
关键: 从结果 20 出发倒推: (20+8)/2-10 = 4。逆运算顺序与题目叙述完全相反。
{"knowns": {"final": {"value": 20, "unit": ""}}, "unknowns": ["target"], "equations": ["(target + 10) * 2 - 8 - final"], "answer_expr": "target", "answer_unit": "", "steps": ["最后是减8 → 倒推先加8: 20+8=28", "之前是乘2 → 倒推除2: 28/2=14", "最先是加10 → 倒推减10: 14-10=4"], "pipeline": [{"step":1,"title":"逆推减8","formula":"20+8=28","eval":"params.final + 8","result_unit":""},{"step":2,"title":"逆推乘2","formula":"28/2=14","eval":"results[1] / 2","result_unit":""},{"step":3,"title":"逆推加10","formula":"14-10=4","eval":"results[2] - 10","result_unit":""}], "visual": {"kind": "flow"}, "question_focus": "原数", "misconception_hint": "倒推顺序 = 题目运算的完全逆序; '一半又多a' 类含分数动作时逆推为 (值+a) 后 ×2 — 逐层验算一遍"}
关键: 正向验证一遍 (4+10=14, ×2=28, -8=20 ✓) 确认无误; 含"一半多a/少a"
   的题用逆向逐层还原, 注意"运出一半少1"意为剩下一半多1。

范例7 (年龄倍数时刻类 — 年龄差恒不变, 求"几岁/哪年"时成 k 倍):
题: 1997年爸爸45岁，儿子9岁，当儿子多少岁时爸爸的年龄是儿子的4倍？
关键推导: 年龄差恒不变 = 45-9 = 36。设儿子 x 岁时成 4 倍: 爸爸当时 = x+36 (爸爸也长了同样的年数, 不能用 45-x) → x+36 = 4x → 3x = 36 → x = 12。
{"knowns": {"age_father": {"value": 45, "unit": "岁"}, "age_child": {"value": 9, "unit": "岁"}, "multiple": {"value": 4, "unit": ""}}, "unknowns": ["target"], "equations": ["target + (age_father - age_child) - multiple*target"], "answer_expr": "target", "answer_unit": "岁", "steps": ["年龄差不变: 45-9=36", "成4倍时: 儿子x岁, 爸爸 x+36 (两人都长大)", "x+36=4x → x=12"], "pipeline": [{"step":1,"title":"年龄差","formula":"45-9=36","eval":"params.age_father - params.age_child","result_unit":"岁"},{"step":2,"title":"解 x+36=4x","formula":"x=36/(4-1)=12","eval":"results[1] / (params.multiple - 1)","result_unit":"岁"}], "visual": {"kind": "timeline"}, "question_focus": "儿子几岁时", "misconception_hint": "爸爸的年龄也在增长 — 未来时态用 x+差, 不是 45-x; '几年前'用差-x, '几年后/几岁时'用 x+差, 方程 (差) = (k-1)*x"}
关键: 目标是"几岁时"→ 方程 x + age_gap = k*x (两边同时成长);
   目标是"几年前"→ 方程 age_father - x = k*(age_child - x)。

范例8 (复杂平均数类 — 部分均值推单值 / 改数后新均值):
题A: 小明前四次测验平均 89 分, 第五次后平均提到 90, 第五次多少分?
关键: 用"总分"桥接 — 前四次总分 89*4=356, 五次总分 90*5=450, 第五次 = 450-356 = 94。易错: 不能用 (90-89)*5, 平均数不能直接相减乘次数。
题B: 六个数平均 27, 其中一个数改为 33 后平均变 30, 原数多少?
关键: 新总分 - 旧总分 = 33 - 原数 → 30*6 - 27*6 = 18 = 33 - 原数 → 原数 = 33 - 18 = 15。改成更大的数平均才会升, 所以 原数 = 新数 - 总分差 (减法, 不是加法)。
{"knowns": {"old_avg": {"value": 89, "unit": "分"}, "old_count": {"value": 4, "unit": "次"}, "new_avg": {"value": 90, "unit": "分"}, "new_count": {"value": 5, "unit": "次"}}, "unknowns": ["target"], "equations": ["target - (new_avg*new_count - old_avg*old_count)"], "answer_expr": "target", "answer_unit": "分", "steps": ["前四次总分 89*4=356", "五次总分 90*5=450", "第五次 = 450-356 = 94"], "pipeline": [{"step":1,"title":"旧总分","formula":"89*4=356","eval":"params.old_avg*params.old_count","result_unit":"分"},{"step":2,"title":"新总分","formula":"90*5=450","eval":"params.new_avg*params.new_count","result_unit":"分"},{"step":3,"title":"第五次成绩","formula":"450-356=94","eval":"results[2] - results[1]","result_unit":"分"}], "visual": {"kind": "flow"}, "question_focus": "第五次成绩", "misconception_hint": "平均数不能直接相减, 必须经总分桥接 (avg*count)"}
关键: 一切复杂平均数题都经"总分 = 平均×个数"桥接; 改数题
   新旧总分之差 = 改动值, 逆推原数。

范例9 (移多补少/转移类 — 变化前后守恒, 差的一半是移动量):
题: 甲乙两桶油共 40 千克, 从甲倒 5 千克给乙后两桶同样重, 甲原来多少?
关键: 倒 5 后相等 → 原来甲比乙多 2*5=10 (移动量=差的一半) → 甲 = (40+10)/2 = 25, 乙 = 15。
{"knowns": {"total": {"value": 40, "unit": "千克"}, "moved": {"value": 5, "unit": "千克"}}, "unknowns": ["target"], "equations": ["target + target - 2*moved - total"], "answer_expr": "target", "answer_unit": "千克", "steps": ["倒5后相等 → 原甲-原乙 = 2*5=10", "甲 = (40+10)/2 = 25", "乙 = 40-25 = 15"], "pipeline": [{"step":1,"title":"原来差","formula":"2*5=10","eval":"2*params.moved","result_unit":"千克"},{"step":2,"title":"甲桶","formula":"(40+10)/2=25","eval":"(params.total + results[1]) / 2","result_unit":"千克"}], "visual": {"kind": "bar_model"}, "question_focus": "甲桶原重", "misconception_hint": "移动 m 后相等 → 原差是 2m 不是 m; 和差问题: 大数=(和+差)/2"}
关键: "移动 m 后相等"→原差=2m; 再套和差公式 大数=(和+差)/2。

范例10 (页码/逐位计数类 — 统计某数字出现次数, 按位分别数后求和):
题: 一本故事书共200页，页码中共用了多少个数字'3'？
关键推导: 逐位统计, 同一个数含多个'3'要算多次 (33 贡献 2 个'3', 不去重!)。
个位是3: 3,13,23,...,193 共 20 个; 十位是3: 30-39,130-139 共 20 个 (33 算 1 个十位3 + 1 个个位3, 两处都算); 百位是3: 1-200 无 → 0; 总计 20+20+0 = 40。
{"knowns": {"units_count": {"value": 20, "unit": "个"}, "tens_count": {"value": 20, "unit": "个"}, "hundreds_count": {"value": 0, "unit": "个"}}, "unknowns": ["target"], "equations": ["target - units_count - tens_count - hundreds_count"], "answer_expr": "target", "answer_unit": "个", "steps": ["个位是3: 3,13,...,193 共20个", "十位是3: 30-39,130-139 共20个 (33 算两个'3', 不去重)", "百位无3", "20+20+0=40"], "pipeline": [{"step":1,"title":"个位3","formula":"20","eval":"params.units_count","result_unit":"个"},{"step":2,"title":"十位3","formula":"20","eval":"params.tens_count","result_unit":"个"},{"step":3,"title":"合计","formula":"20+20+0=40","eval":"results[1] + results[2] + params.hundreds_count","result_unit":"个"}], "visual": {"kind": "grid"}, "question_focus": "数字3出现总次数", "misconception_hint": "逐位计数不按数去重 — 33 含两个'3'要算 2 次; 先逐位枚举填 knowns, 再求和"}
关键: 枚举计数题的列式范式 — 每个位/每类的数量由枚举得出后填进 knowns
   (个位3每10页1次、十位3每100页10次), 方程只做求和 target − 各类计数。

范例11 (封闭双层栽树类 — 封闭路线: 间隔数=棵数; 双层再乘每间隔棵数):
题: 圆形池塘周长240米，沿池塘周围每隔8米栽一棵柳树，再在每相邻两棵柳树之间等距离栽2棵桃树，一共栽树多少棵？
关键推导: 封闭路线棵数=间隔数 → 柳树 = 240/8 = 30; "每相邻两棵柳树之间栽2棵桃树" → 桃树 = 30*2 = 60; 共 30+60 = 90。这不是逻辑矛盾 — "柳树之间"指相邻柳树的间隔, 桃树栽在间隔里。
{"knowns": {"length": {"value": 240, "unit": "米"}, "spacing": {"value": 8, "unit": "米"}, "peach_per_gap": {"value": 2, "unit": "棵"}}, "unknowns": ["target"], "equations": ["target - length/spacing - length/spacing*peach_per_gap"], "answer_expr": "target", "answer_unit": "棵", "steps": ["封闭路线: 柳树=周长/间距=240/8=30", "桃树=柳树数×每间隔棵数=30*2=60", "共 30+60=90"], "pipeline": [{"step":1,"title":"柳树","formula":"240/8=30","eval":"params.length / params.spacing","result_unit":"棵"},{"step":2,"title":"桃树","formula":"30*2=60","eval":"results[1] * params.peach_per_gap","result_unit":"棵"},{"step":3,"title":"合计","formula":"30+60=90","eval":"results[1] + results[2]","result_unit":"棵"}], "visual": {"kind": "grid"}, "question_focus": "一共栽树棵数", "misconception_hint": "封闭路线间隔数=棵数 (不+1不-1); 每间隔栽 a 棵第二层树 → 第二层 = 第一层×a"}
关键: 封闭路线 (环形/池塘/一圈) 棵数 = 周长/间距, 严格等于间隔数;
   "每相邻两棵A之间栽 b 棵B" → B = A棵数 × b, 分层算完再求和。

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


def _eval_safe(expr: str, extra_names: set[str] | None = None) -> bool:
    """静态校验 eval 串 — 算术 + params.x/results[n] + extra_names (判断题判据裸名)。"""
    allowed = {"params", "results"} | (extra_names or set())
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
        if isinstance(node, ast.Name) and node.id not in allowed:
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
    # 判断题判据裸变量名 (side1 等) — 安全校验 (_eval_safe extra_names) 已限定范围
    if isinstance(node, ast.Name) and node.id in params:
        return float(params[node.id])
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


def parse_judgment(raw: str) -> dict[str, Any] | None:
    """解析判断型题 (question_kind=judgment) 输出 — criterion 必须合法。"""
    from ...._parse import parse_json
    data = parse_json(raw)
    if not isinstance(data, dict) or str(data.get("question_kind", "")) != "judgment":
        return None
    knowns_raw = data.get("knowns")
    if not isinstance(knowns_raw, dict) or not knowns_raw:
        return None
    knowns: dict[str, float] = {}
    for name, item in list(knowns_raw.items())[:12]:
        if not isinstance(name, str) or not name.isidentifier():
            continue
        val = item.get("value") if isinstance(item, dict) else item
        try:
            knowns[name] = float(val)
        except (TypeError, ValueError):
            continue
    if not knowns:
        return None
    crit_raw = data.get("criterion")
    if not isinstance(crit_raw, dict):
        return None
    expr = str(crit_raw.get("expr", ""))
    if not expr or not _eval_safe(expr, extra_names=set(knowns)):
        return None
    return {
        "knowns": knowns,
        "criterion_expr": expr[:200],
        "true_meaning": str(crit_raw.get("true_meaning", "成立"))[:120],
        "false_meaning": str(crit_raw.get("false_meaning", "不成立"))[:120],
        "steps": [str(s)[:120] for s in data.get("steps", [])[:5] if isinstance(s, str)],
        "visual": _sanitize_visual(data.get("visual")),
        "misconception_hint": str(data.get("misconception_hint", ""))[:120],
        "question_focus": str(data.get("question_focus", ""))[:60],
    }


def solve_judgment(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """执行判据表达式 (受限 AST), 返回 {criterion_value, verdict, verdict_text}。"""
    try:
        tree = ast.parse(parsed["criterion_expr"], mode="eval")
        val = float(_ast_eval(tree.body, parsed["knowns"], {}))
    except Exception:
        return None
    if val != val or val in (float("inf"), float("-inf")):
        return None
    is_true = val > 0
    return {
        "criterion_value": val,
        "verdict": is_true,
        "verdict_text": parsed["true_meaning"] if is_true else parsed["false_meaning"],
    }


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
