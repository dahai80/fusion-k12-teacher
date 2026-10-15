# GUIDE 05 — 360 全量验收

> 脚本：`scripts/05-360验收/e2e_bnup_eval.py`（`--direct-mlx` 直连 11434）
> 通过标准：**PRD math ≥ 89%**（对照 4B 基线 42.9%）
> 前置：DPO 已 merge（guides/04 §3）

## 1. 评测集

- 360 题：PRD 场景全集（28 题冒烟是其子集），含易错题场景
  （`cylinder_cone_cut` 等，见 `scene_compiler.py` / `sympy_verifier.py`）。
- 数值比对容差 ε=0.01（`fusion_k12_teacher/eval/eval_harness.py`）。

## 2. 执行

```bash
cd ~/fusion/fusion-k12-teacher
python3 scripts/e2e_bnup_eval.py --direct-mlx \
  --base-url http://localhost:11434/v1 --api-key fg-admin-key
```

- **务必 `--direct-mlx`**：经 gateway 11432 会因 import fusion_core 卡住。
- 评测时段不得与训练重叠（显存争抢，见 guides/99）。

## 3. 判读

| 指标 | 4B 基线 | 通过标准 |
|---|---|---|
| PRD math 正确率 | 42.9% | **≥ 89%** |
| JSON 可解析 | 96.4% | 不低于基线 |
| Schema 命中 | 89.3% | 不低于基线 |
| E1 参数名不一致 | 头号失败 | 大幅收敛（回归 param_drift 场景） |

分场景出报告：按题型/年级/场景 handler 分桶看失败分布，SysPy handler 报错单独统计。

## 4. 结果归档

- 明细 JSON/CSV 存 `train/data/04-评估集/`（文件名带日期与 checkpoint 标识）。
- 汇总（各指标 + 通过/不通过结论）追加到 `train/data/99-状态与恢复/STATUS.md`。
- 不通过 → 按失败分布定位（数据缺口 / handler bug / β 调参），回到对应 guide 重跑该段。

## 5. 收尾

- 通过后：按 `materials/01-架构方案` 的发布段走部署（local/cloud 双形态开关 `FUSION_MLX_CLOUD`）。
- 清理：临时进程、/tmp 日志、未留底 checkpoint；只保留最终产物与本目录归档。
