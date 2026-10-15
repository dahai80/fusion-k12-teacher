# GUIDE 02 — SFT 训练（fusion-trainer → fusion-mlx）

> 配置：`materials/03-SFT训练/bnup_sft_32b.yaml`（8-bit QLoRA/DoRA r16，5700 步，batch=2，lr=1e-4）
> 数据：`data/02-SFT/sft_v1.jsonl`（冻结）　底座：`mlx-community/Qwen2.5-32B-Instruct-4bit`
> 入口：`python -m fusion_trainer.cli`（系统 python3.12）

## 1. 前置检查

```bash
# 引擎健康（必须 200）
MKEY=$(python3 -c "import json;print(json.load(open('/Users/dahai/.fusion-mlx/settings.json')).get('auth',{}).get('api_key',''))")
curl -s -m 8 http://127.0.0.1:11434/ -H "Authorization: Bearer $MKEY" | head -1

# 无残留训练 job / trainer 进程
ps aux | grep '[b]nup-train' ; curl -s http://127.0.0.1:11434/admin/api/fine-tune/jobs \
  -H "Authorization: Bearer $MKEY" -H "X-Fusion-Route: admin" | jq '[.[]|select(.status=="running")]|length'
```

## 2. 启动（必须由长驻宿主持有）

```bash
cd ~/fusion/fusion-trainer
FUSION_MLX_PORT=11434 \
FUSION_MLX_ADMIN_TOKEN=$MKEY \
python3 -m fusion_trainer.cli sft \
  --config ~/fusion/fusion-k12-teacher/train/materials/03-SFT训练/bnup_sft_32b.yaml \
  --model mlx-community--Qwen2.5-32B-Instruct-4bit \
  --dataset ~/fusion/fusion-k12-teacher/train/data/02-SFT/sft_v1.jsonl \
  --run-name bnup_sft_32b_v2 \
  2>&1 | tee /tmp/bnup_sft_trainN.log
# 或直接: bash train/scripts/20-sft.sh (env 定义见 00-env.sh, ADAPTER_NAME 可覆盖)
```

- **宿主规则**：训练 job 必须挂在长驻会话（AtomCode `bash_start`/tmux）上。
  父 shell 退出会连带 cancel mlx job（v3~v5 死因）。
- **run-name 规则**：重训一律换新 `--run-name`（v2/v3…），不覆写旧 adapter 目录；
  v1 `bnup_sft_32b` 无效已弃（训练丢 system 字段，fusion-trainer#69/PR#70）。
- 训练期间**不得**向 mlx 发推理请求（峰值 87.8GB/128GB，争抢会触发 fatal，见 guides/99）。

## 3. 监控

```bash
MKEY=…; JOB=97b7a986971e
curl -s http://127.0.0.1:11434/admin/api/fine-tune/jobs/$JOB \
  -H "Authorization: Bearer $MKEY" -H "X-Fusion-Route: admin" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);p=d.get('progress') or {};\
print(d.get('status'), p.get('step'),'/',p.get('total_steps'), 'loss', p.get('train_loss'), \
'tok/s', round(p.get('tokens_per_second') or 0), 'mem', p.get('peak_memory_gb'))"
```

- 正常曲线：loss 1.6 → 0.14（~500 步内），tok/s 160~290，显存 64~88GB。
- checkpoint 每 100 步落盘：`~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/<ADAPTER_NAME>/000NNNN_adapters.safetensors`（当前 `bnup_sft_32b_v2`）。
- 快照留底（可选）：拷贝到 `train/checkpoints/` 并更新 `SHA256SUMS.txt`。

## 4. 完成判据

- status = `completed`，最终 `adapters.safetensors` = step 5700 权重。
- 手动快照到 `train/checkpoints/bnup_sft_32b_final.safetensors`。

## 5. 中断处理（重要）

**两档处置**：

- **权重级续跑（推荐）**：`RESUME=1 ./20-sft.sh`（或 `run_all.sh` 前置该变量）。
  trainer `--resume` 自动找最新 checkpoint → fusion-mlx `init_adapter_path` 恢复权重
  （#1182/#65 已落地，要求 fusion-mlx ≥ v0.10.13）。注意语义：**step 从 0 重计、
  optimizer state 不恢复**——是"更好起点的新 5700 步周期"，最多丢最近一个
  checkpoint（100 步）的权重。
- **从零重跑**：`RESUME=0`（默认）。仅在数据/配置变更后使用。
- 引擎重启/进程被杀 → job 在内存中随之丢失 → checkpoint 仍在磁盘上，按上面续跑即可。
  恢复步骤与根因见 `guides/99-状态与恢复/GUIDE.md`。
