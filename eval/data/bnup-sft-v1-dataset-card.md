# bnup-sft-v1 / dpo-v1 数据集（sft-dpo-1013 §2，已冻结）

冻结时间: 2026-10-13 | 生成种子: 2026 | 合成器: scripts/bnup_synth.py
变更规则: 只增不改 — v2 迭代沿用同一管线新开版本号，禁止原地修改。

## 文件

| 文件 | 内容 | 规模 |
|------|------|------|
| `raw_sft_v1.json` | 合成器原始输出 {question, thinking, dsl, template_id, grade, split} | 4000（train 3800 / holdout 200）|
| `sft_v1.jsonl` | `ft bnup-prep --stage sft` 产物（ShareGPT/Alpaca，`<thinking>`+`<dsl>` 两段式）| 4000 条 |
| `dpo_v1.jsonl` | `ft bnup-prep --stage dpo --neg-ratio 3` 产物（chosen+rejected 偏好对）| 12000 对 |

## 质量闸（全量重放 PASS，0 失败）

- gate1 JSON roundtrip / gate2 k12 DSL_SCHEMA / gate3 eval 引用键名==parameters 键（双向）+ results[n] 只引用已有步 + ASCII 运算符 / gate4 生产求值器（BNUPEvaluator）复算 == 独立算术 expect（ε=0.01）
- v3 严格 schema（fusion-core SOCRATIC_DSL_V3，bnup_prep 训练闸）：4000/4000 通过
- E4 舍入修正基线：42.9%（harness ε=0.01）

## 关键设计（直击 E1 参数名漂移 —— e2e_28final 10/18 可修复失败）

1. **变量表 SSoT**：question/thinking/parameters/pipeline.eval 全部从同一 vars dict 渲染，eval 键名与 parameters 定义 by construction 一致
2. **thinking 四段固定结构**，第 3 段显式示范"键名核对：eval 引用 {…} 与 parameters 键名逐字一致 ✓"
3. **逆构采样**：先采样中间量反推题面量，ground_truth 整洁且可被 eval 精确复算

## DPO 负例类型分布（12000 对）

| 类型 | 占比 | 说明 |
|------|------|------|
| **param_drift** | **66.7%**（8000） | eval 引用未定义参数名——中文同义（每排/长度）、缩写（cols）、大小写漂移（T_bridge）、后缀漂移，词表来自 e2e_28final 真实 E1 失败 |
| broken_json | 13.2% | JSON 截断/非法 token |
| structural | 6.6% | 缺 schema 必填字段（format_drift） |
| 静态负例 | 6.6% | direct_answer（跳过 thinking）/missing_tag/wrong_visual_type |
| no_json | 7.0% | 无 DSL 块 |

负例生成器：fusion-trainer `bnup_negatives.py`（新增 `make_param_drift`，测试 22/22 绿）。

## 模板覆盖（38/38）

行程家族（train_crossing_bridge/train_on_bridge/relative_motion/two_trains_meet/overtake/echo/basic_motion/round_trip）、离散计数（cutting_segments/queue_counting/overlap_splice/redundant_filter/fold_cut/tree_planting×4模式）、几何（sprinkler_area/displacement_volume/cuboid_combine_surface/semicircle_perimeter/rectangle_area/cylinder_cone_cut）、比例盈亏（chicken_rabbit/sum_multiple/profit_loss）、统计（average_problem/statistics_mean/equal_division）、归一单价（unitary_method/unitary_combined/tiered_pricing/simple_interest/work_problem/weekday_calc×分支）、阵列组合（array_counting/combination_count/stars_bars）、四则方程（arithmetic/linear_equation）。

## 冻结校验和（SHA256 前 16 位）

```
raw_sft_v1.json  f2791951dc852526…
sft_v1.jsonl     3ea91057ad715e17…
dpo_v1.jsonl     3c5018bdd5ce5b9f…
```

数据文件本体不入 git（根目录 `/data/` 在 .gitignore，37MB 大文件走对象存储/训练机同步）；
本 README + 校验和 + 合成器（scripts/bnup_synth.py）+ 负类（fusion-trainer bnup_negatives.py）入库，
任何机器可按同一 seed=2026 确定性复现。
