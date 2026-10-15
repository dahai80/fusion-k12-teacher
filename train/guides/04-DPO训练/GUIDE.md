# GUIDE 04 — DPO 训练（β=0.1 链式 SFT adapter）

> 配置：`materials/05-DPO训练/bnup_dpo_32b.yaml`（β=0.1）
> 数据：`data/03-DPO/dpo_v1.jsonl`（冻结，含 param_drift 负类）
> 前置：中评 gate 通过（guides/03，eval_exec ≥ 85%）

## 1. 链式初始化（核心）

DPO 从 **SFT adapter 权重出发**，不是从底座裸跑：

- fusion-mlx DPO 服务端已有 `init_adapter_path` 先例
  （`fusion_mlx/training/dpo_service.py:270-278`），SFT 侧没有（那是 #1182 的事）。
- 启动时把 `init_adapter_path` 指向 SFT 产物
  `~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b_v2/adapters.safetensors`。

## 2. 启动

```bash
cd ~/fusion/fusion-trainer
FUSION_MLX_PORT=11434 \
FUSION_MLX_ADMIN_TOKEN=$MKEY \
python3 -m fusion_trainer.cli bnup-train --stage dpo \
  --model mlx-community--Qwen2.5-32B-Instruct-4bit \
  --sft-data ~/fusion/fusion-k12-teacher/train/data/02-SFT/sft_v1.jsonl \
  --dpo-data ~/fusion/fusion-k12-teacher/train/data/03-DPO/dpo_v1.jsonl \
  --init-adapter-path ~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b_v2
```

（`--sft-data` 是 typer 必填项（dpo 阶段不读它）；或直接 `bash train/scripts/40-dpo.sh`，
ADAPTER_NAME 与 00-env.sh 同源。配置细节读 `materials/05-DPO训练/bnup_dpo_32b.yaml`。）

监控方式与 guides/02 §3 相同（同一 jobs API）。

## 3. Merge

DPO 完成后得到独立 adapter 目录。验收前需要把 LoRA **merge 进底座权重**导出完整模型
（按 fusion-mlx 提供的 export/merge 能力操作；merge 后模型归档路径记录到 STATUS.md）。

## 4. 判据与归档

- DPO status = `completed`，chosen/rejected margin 曲线无发散。
- merge 后模型进入 360 验收（guides/05）；DPO job id 与 adapter 路径追加到
  `train/data/99-状态与恢复/STATUS.md`。

## 5. 已知坑

- β=0.1 是保守起点：margin 若快速饱和（几百步内拉满）说明 β 偏大，回配置调小重跑。
- param_drift 负类直接决定"换参数必须重算"行为——验收时重点回归该模式（E1 类）。
- 训练期间同样遵守"不向 mlx 发推理"红线（guides/99）。
