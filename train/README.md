# Fusion-K12-Teacher 微调全量材料（train/）

> 本目录是 BNUP 32B 微调线（SFT → 中评 gate → DPO → 360 全量验收）的**唯一归档点**：
> 材料（materials）、指导（guides）、数据（data）、脚本（scripts）、权重快照（checkpoints）
> 五大类，按 01→06 流水线步骤分子目录。数据本体不入 git，靠 `SHA256SUMS.txt` 校验 + 脚本可复现。

## 流水线总览

```
01-数据工程 ──→ 02-SFT训练 ──→ 03-中评gate ──→ 04-DPO训练 ──→ 05-360验收 ──→ 06-发布
 bnup_synth      QLoRA-8bit     serve路径         β0.1 链式       PRD math ≥89%
 四道闸冻结      r16 / 5700步   28题冒烟         SFT adapter     e2e_bnup_eval
 sft/dpo v1     checkpoint     eval_exec≥85%    merge 权重      对照 4B 基线
```

## 目录结构

```
train/
├── README.md                    ← 本文件（总览 + 使用说明）
├── SHA256SUMS.txt               ← 全部文件校验和（shasum -a 256 -c SHA256SUMS.txt）
├── materials/                   ← 材料：方案、配置、参考（只读归档）
│   ├── 01-架构方案/  fusion-k12-teacher-sft-dpo-1013.md（微调总方案）
│   ├── 02-数据工程/  bnup-sft-v1-dataset-card.md（数据卡）
│   ├── 03-SFT训练/   bnup_sft_32b.yaml（SFT 配置：8-bit QLoRA r16）
│   ├── 05-DPO训练/   bnup_dpo_32b.yaml（DPO 配置：β=0.1）
│   ├── 04-中评gate/  （空：gate 标准见 guides/03-中评gate）
│   ├── 06-360验收/   （空：验收标准见 guides/05-360验收）
│   └── 99-状态与恢复/（空：运行时状态看 data/99-状态与恢复 + guides/99）
├── guides/                      ← 指导：每一步怎么做（操作手册）
│   ├── 01-数据工程/  GUIDE.md — 四道闸、param_drift 负类、冻结校验
│   ├── 02-SFT训练/   GUIDE.md — bnup-train 启动、监控、断点坑
│   ├── 03-中评gate/  GUIDE.md — serve 路径 28 题冒烟（adapter 挂载 + SFT prompt），阈值与判读
│   ├── 04-DPO训练/   GUIDE.md — 链式 adapter、merge、init_adapter_path
│   ├── 05-360验收/   GUIDE.md — 全量评测、基线对照、通过标准
│   └── 99-状态与恢复/ GUIDE.md — 已知坑全集 + 故障恢复 runbook
├── data/                        ← 数据：冻结数据集 + 运行时状态
│   ├── 01-数据工程/  （空：原始语料不入库，见数据卡复现方式）
│   ├── 02-SFT/       sft_v1.jsonl（冻结，SHA256 见校验文件）
│   ├── 03-DPO/       dpo_v1.jsonl（冻结）
│   ├── 04-评估集/    （空：28/360 题评估集经 e2e 脚本从库内生成）
│   └── 99-状态与恢复/（训练历史日志；当前状态见 STATUS.md）
├── scripts/                     ← 脚本：一键启动 + 分步入口
│   ├── 00-env.sh                ← 环境变量/路径唯一定义处（改配置只动这里）
│   ├── 10-check-env.sh          ← 步骤 0 环境预检
│   ├── 20-sft.sh                ← 步骤 1 SFT（含断点跳过 + 终态轮询 + 快照）
│   ├── 30-midgate.sh            ← 步骤 2 中评 gate（阈值硬门槛）
│   ├── 40-dpo.sh                ← 步骤 3 DPO
│   ├── 50-accept.sh             ← 步骤 4 360 验收
│   ├── run_all.sh               ← 一键总控（--from / --dry-run）
│   ├── 01-数据工程/  bnup_synth.py
│   ├── 03-中评gate/  midgate_direct_lm.py（引擎外直载 fallback，serve 乱码复现时用）
│   └── 05-360验收/   e2e_bnup_eval.py
└── checkpoints/                 ← 权重快照（体积大，按需保留）
    ├── bnup_sft_32b_best_0000500.safetensors
    ├── bnup_sft_32b_0000400.safetensors
    └── bnup_sft_32b_latest.safetensors
```

## 快速使用

### 一键启动（推荐）

```bash
cd ~/fusion/fusion-k12-teacher/train/scripts

./run_all.sh              # 全链：预检 → SFT → 中评 gate → DPO → 360 验收
./run_all.sh --from mid   # 从中评 gate 开始（SFT 已有产物时）
./run_all.sh --dry-run    # 只预检与产物检查，不实际训练（演练）
```

- **断点续跑**：每步先查产物，存在即自动跳过（如 `adapters.safetensors` 在位则 SFT 跳过）；
  从某步重启用 `--from sft|midgate|dpo|accept`。
- **常用环境变量**（见 `scripts/00-env.sh`）：
  `FORCE_SFT=1` 强制重跑 SFT；`RESUME=1` SFT 断点续跑（从最新 checkpoint 权重继续，
  step 从 0 重计、optimizer state 不恢复，fusion-mlx #1182）；
  `GATE_MIN_EVAL_EXEC=85` 中评阈值；
  `ACCEPT_MIN_MATH=89` 验收阈值；`DPO_DONE=1` 跳过 DPO。
- 步骤失败即停（gate 是硬门槛），恢复照 `guides/99-状态与恢复/GUIDE.md` §B2。
- 日志落 `data/99-状态与恢复/`，评测产物落 `data/04-评估集/`。

### 手动分步

每步独立可跑（均先做预检）：

```bash
cd ~/fusion/fusion-k12-teacher/train/scripts
./10-check-env.sh   # 环境预检（引擎/key/底座/数据/内存净空）
./20-sft.sh         # 步骤 1 SFT（5700 步）
./30-midgate.sh     # 步骤 2 中评 gate（28 题，eval_exec ≥ 85）
./40-dpo.sh         # 步骤 3 DPO（β=0.1 链式）
./50-accept.sh      # 步骤 4 360 验收（math ≥ 89）
```

### 材料校验

```bash
cd ~/fusion/fusion-k12-teacher/train
shasum -a 256 -c SHA256SUMS.txt
# 数据/脚本如有变更：重新生成校验和
find . -type f \( -name "*.jsonl" -o -name "*.safetensors" -o -name "*.yaml" \
  -o -name "*.py" -o -name "*.md" -o -name "*.sh" \) ! -name SHA256SUMS.txt \
  ! -name STATUS.md ! -name "*.log" \
  -exec shasum -a 256 {} + | sort -k2 > SHA256SUMS.txt
```

## 关键约定（不变量）

- **数据本体不入 git**：数据卡（materials/02）记录校验和与 seed，`bnup_synth.py` 可复现。
- **API key 严禁入库**：全部经环境变量（`FUSION_MLX_ADMIN_TOKEN` 等），未设置报错退出。
- **LLM 不产出数值**：SymPy 覆写为唯一数值 SSoT（架构方案 §3）。
- **失败降级不编造**：引擎返回 default dataclass + `.error`，评测如实记录失败样本。
- **checkpoint 不可续训**（fusion-mlx#1182 未落地）：引擎重启 = 从零重跑，权重快照仅作留底。

## 当前状态（2026-10-15）

- **训练已全部停止，未执行微调**（用户指令）：v16 job 已取消，无 running job。
- 一键启动脚本就绪并 dry-run 验证通过：`scripts/run_all.sh`（断点续跑、--from 跳段、--dry-run 演练）。
- 历史最高完整落盘点 **0000500**（已快照至 checkpoints/）。
- 根因已定位并提 issue：**fusion-mlx#1205**（memory_enforcer 超限 fatal_exit 连带 cancel），
  **fusion-trainer#65**（无断点续训 + 无引擎重启检测），另 **fusion-mlx#1182**（resume 支持）。
- 详细运行史与恢复步骤见 `guides/99-状态与恢复/GUIDE.md` 与 `data/99-状态与恢复/STATUS.md`（v0.10.13 起支持 RESUME=1 权重级续跑）。
- 待用户指令后执行：`scripts/run_all.sh`（或指定 `--from` 起点分段跑）。
