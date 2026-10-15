# GUIDE 03 — 中评 gate（28 题冒烟，serve 路径 + 微调 adapter）

> 脚本：`train/scripts/30-midgate.sh`　评估主入口：`scripts/e2e_bnup_eval.py`
> SFT 完成后必须过本 gate，才能进入 DPO（guides/04）。

## 1. 为什么走 serve

2026-10-16 前的"serve 长生成乱码"根因已定位：fusion-mlx 对 32B 自动开启
TurboQuant 4-bit KV cache（fusion-mlx **#1230**），已在
`~/.fusion-mlx/model_settings.json` per-model `turboquant_kv_enabled: false`
关闭并重启验证，serve 输出干净。**serve 即生产路径**，gate 必须覆盖真实服务链路
（adapters 请求字段挂载 + SFT 同分布 system prompt + SSE streaming）。

引擎外直载 runner 保留在 `scripts/03-中评gate/midgate_direct_lm.py`，仅在
乱码复现（#1230 修复前）时作 fallback。

## 2. 前置

- SFT 已完成：`adapters.safetensors` 在
  `~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b_v2/`
  （`ADAPTER_NAME` 可覆盖，见 00-env.sh；v1 `bnup_sft_32b` 无效已弃——
  训练丢 system 字段，fusion-trainer#69/PR#70）。
  **注意**：`adapters.safetensors` 在 checkpoint 期（~step 100+）就会落盘，文件存在 ≠ 训练完成；
  30-midgate.sh 会查 jobs API 终态（`require_sft_done`），训练中一律拒绝。
- fusion-mlx 已起（`~/fusion/fusion-mlx/start.sh start`），且 model_settings.json
  已对 32B 关闭 turboquant_kv_enabled（30-midgate.sh 会前置校验）。
- 训练期间内存紧张已解除（无其他大进程）。

## 3. 执行

```bash
cd ~/fusion/fusion-k12-teacher
bash train/scripts/30-midgate.sh          # serve 路径, 28 题, ~1-2h (32B ~1.3 tps)
# 或直接调评估器:
python3 scripts/e2e_bnup_eval.py --direct-mlx --stream \
  --model mlx-community--Qwen2.5-32B-Instruct-4bit \
  --adapters ~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b_v2 \
  --testset train/data/04-评估集/e2e_28.json --prompt-style sft --concurrency 2
```

## 4. 判读（阈值）

| 指标 | 阈值 | 说明 |
|---|---|---|
| eval_exec | **≥ 85%** | 场景编译可执行率（硬门槛，不过不得进 DPO） |
| JSON 可解析 | 参考 4B 基线 96.4% | 结构健康度 |
| Schema 命中 | 参考 4B 基线 89.3% | 键名一致性 by construction |
| 数学正确率 | 参考 4B 基线 36%（应显著提升） | SymPy 覆写后的 eval 数值 |

头号失败模式（4B 基线）：**E1 参数名不一致**——重点看 32B 是否修复。

## 5. 结果归档

- 输出 JSON 存 `train/data/04-评估集/midgate_<日期>.json`（30-midgate.sh 自动），
  摘要追加到 `train/data/99-状态与恢复/STATUS.md`。
- gate 通过 → 进 guides/04（DPO）；不通过 → 按失败样本回改数据/配置，重跑 SFT（guides/02）。

## 6. 已知坑

- e2e runner **不要**经 gateway 11432 跑（import fusion_core 会卡住）；
  28 题评估用 `--direct-mlx`（base_url=localhost:11434/v1，key=fg-admin-key）。
- 32B ~1.3 tps：必须 `--stream`（SSE 绕 600s 非 streaming 上限），28 题
  concurrency 2 约 1-2 小时。
- `--prompt-style sft` 用训练同款 system prompt（北师大苏格拉底讲师）才是
  同分布评估；`eval` 风格是 harness 详细格式说明，用于跨模型横评。
- 32B 输出乱码 = TurboQuant KV 又开了（检查 model_settings.json + 重启），
  见 guides/99 §A 乱码行。
- 28 题冒烟与 360 全量共用同一评测框架，区别仅在题集规模与通过阈值。
