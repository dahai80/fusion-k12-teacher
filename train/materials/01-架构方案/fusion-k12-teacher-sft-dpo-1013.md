# fusion-k12-teacher 模型微调详细方案 — SFT + DPO（BNUP-Final）

**日期**: 2026-10-13
**目标**: 将基座模型（当前 Qwen3.5-4B，目标 Qwen2.5-32B-Instruct）微调为 `Qwen2.5-32B-BNUP-Final`，通过 28 题 E2E 评估五步瀑布全部 PRD 阈值（数学准确率 35.7% → ≥89%）
**依据**: `scripts/e2e_results/e2e_28final.json` 真实失败样本逐条分析 + fusion-trainer/fusion-mlx 训练栈现状盘点
**训练硬件**: M5 128GB 统一内存（QLoRA 8-bit 可训 32B）

---

## 0. 现状证据链（为什么必须微调、微调什么）

### 0.1 E2E 28 题五步瀑布基线

| 指标 | 实际 | PRD 目标 | 缺口 |
|------|------|----------|------|
| 标签隔离率 | 100% | 99.5% | ✅ 唯一达标项 |
| JSON 语法率 | 96.4% | 100% | -3.6pp（1 例） |
| Schema 合格率 | 89.3% | 99% | -9.7pp（2 例缺字段） |
| Eval 可执行率 | 50% | 100% | **-50pp（11 例）** |
| 数学准确率 | 35.7% | 89% | **-53.3pp（含舍入误判 2 例）** |

### 0.2 失败样本逐条归因（e2e_28final.json per_sample 权威数据）

| # | 错误模式 | 真实样本（error 原文） | 例数 | 可否 prompt 工程修复 | 微调必要性 |
|---|----------|------------------------|------|----------------------|------------|
| E1 | **eval 引用未定义参数名** | `eval exec: '每排'` `'cols'` `'row_count'` `'T_bridge'` `'L_wire'` `'v_cone'` `'efficiency'` `'mass'` | 8 | ❌ 反复出现，参数名命名空间是模型的"自由发挥区" | **核心 SFT 目标** |
| E2 | eval 语法错误 | `invalid syntax (<string>)`、`eval exec: '31'`（引用了字面量） | 2 | ❌ 同上 | **核心 SFT 目标** |
| E3 | 数学建模错误（公式选错） | `13.33 != 20`（平均分配 vs 总量）、`16.5 != 11` | 2 | ❌ 需要题面→公式映射先验 | **SFT+DPO 双管** |
| E4 | 舍入不一致 | `27.1667 != 27.17`、`14.482 != 14.48` | 2 | ⚠️ 可改 eval 脚本容差（ε=0.01），**不必微调** | 否（建议改 harness） |
| E5 | JSON 截断 | `Expecting ',' delimiter: char 469` | 1 | ⚠️ max_tokens/早停问题 | 可顺带修 |
| E6 | Schema 缺字段 | `'entities' is a required property`、`None is not of type 'object'` | 2 | ❌ | SFT 覆盖 |

**关键结论**: 18 个可微调修复的失败中，**10 例（56%）是同一种错误——eval 表达式引用了 parameters 中未定义的变量名**（或中文名/字面量）。这不是推理能力问题，是**命名一致性问题**——模型缺乏"先定义 parameters 键名，再在 eval 中逐字引用"的纪律。这正是 SFT（示范正确模式）+ DPO（惩罚命名漂移）能确定性解决的类型。剩余 2 例舍入误判建议改 harness 容差（改后基线数学准确率即 35.7%→42.9%）。

### 0.3 训练栈现状（无需新建基础设施）

| 资产 | 位置 | 状态 |
|------|------|------|
| SFT/DPO 训练编排 CLI | `~/fusion/fusion-trainer`（`ft bnup-prep` / `ft bnup-train --stage sft|dpo`） | ✅ 已实现（issue #59） |
| SFT 样本构造器 | `fusion_trainer/dataset/bnup_prep.py::build_sft_sample` → `{instruction, input, output=<thinking>+<dsl>, system}` | ✅ |
| 负样本工厂 | `fusion_trainer/dataset/bnup_negatives.py` — 5 类破坏器（broken_json/direct_answer/wrong_visual_type/missing_tag/format_drift） | ✅（需新增"参数名漂移"类） |
| DPO 偏好对构造 | `bnup_dpo_prep.py` → `{conversations, chosen, rejected}` ShareGPT | ✅ |
| 训练配置 | `configs/bnup_sft_32b.yaml`（QLoRA-8bit r16 α32）/ `bnup_dpo_32b.yaml`（β0.1 sigmoid, init_adapter_path 链接 SFT） | ✅ |
| 训练执行 | fusion-mlx `/admin/api/fine-tune/jobs`（SFT）+ `/fine-tune/dpo/jobs`（DPO），SSE 进度，LoRA in-place swap（#389） | ✅ 运行中 :11434 |
| 评估基准 | `fusion_k12_teacher/eval/data/bnup_benchmark.json` 360 题（in_domain 216/ood 72/adversarial 72）+ `e2e_bnup_eval.py` 五步瀑布 | ✅ |
| Adapter 热切换 | `/admin/api/fine-tune/adapters/{model}/{adapter}/serve`（毫秒级换装，单 base 多 adapter） | ✅ |

**结论: 基础设施完备，本方案 = 数据工程（主力）+ 跑通既有管线 + 评估闭环。**

---

## 1. 目标定义（微调要达成什么）

### 1.1 能力目标（按优先级）

| 优先级 | 能力 | 对应错误 | 度量 |
|--------|------|----------|------|
| P0 | **命名一致性**: parameters 键名定义后，pipeline.eval 逐字引用（含大小写/下划线/禁中文/禁字面量） | E1+E2（10 例） | eval_exec_rate 50%→100% |
| P0 | **DSL Schema 完整性**: meta/parameters/entities/pipeline 四段齐全且类型正确 | E6 | schema_rate 89.3%→100% |
| P1 | **公式选择正确性**: 题面语义 → 正确的 pipeline 公式链（植树/行程/几何/统计…） | E3 | math_accuracy → ≥89% |
| P1 | **JSON 语法稳健**: 单次输出完整合法 JSON（含长 pipeline 不截断） | E5 | json_rate → 100% |
| P2 | **标签纪律**: `<thinking>推理过程</thinking><dsl>JSON</dsl>` 两段式，thinking 中不泄漏 DSL | （已达标，保持） | tag_rate ≥99.5% |

### 1.2 量化验收（gate 标准）

```
28 题冒烟: 五项全部达标（math_accuracy ≥89%，eval_exec 100%）
360 题全量: in_domain math ≥92%（训练分布内应更好）
           ood math ≥75%（泛化底线）
           adversarial math ≥60%（对抗抗性）
           tag/json/schema 三率与 28 题一致（无回归）
```

### 1.3 非目标（明确不做）

- 不改 harness 阈值来"达标"（E4 舍入容差是唯一例外，属 harness bug 修复）
- 不追求通用数学能力提升（只对齐 BNUP DSL 任务分布，通用能力靠基座）
- 不微调对话风格（现有温度/prompt 已够）

---

## 2. 数据工程（本方案的工作量主体）

### 2.1 数据金字塔（总量与配比）

| 层 | 来源 | 条数 | 占比 | 作用 |
|----|------|------|------|------|
| L1 种子示范 | 现有 28 题 E2E 中 **10 个全对样本**（ind-ag-03/11、ind-dc-02、ind-g2d-05、ind-gu-cj-odd-ex-01、ind-bd-07、ood-29、ood-calc-06、adv-train-22 等）人工复核后入库 | 10 | 2% | 黄金标准，锚定格式 |
| L2 规则合成 | **程序化生成器**（见 2.2）：8 大题型 × 参数空间扫描，DSL 由模板引擎生成（**保证 parameters/eval 键名一致性 100%**） | 2400 | 48% | SFT 主体 — 命名一致性靠"生成的数据天然正确"灌输 |
| L3 课标扩展 | `bnup_benchmark.json` 360 题的 ground_truth 反演 + `train_bridge_bank.json` 134 题 × 20 公式卡 + 125 易错点扩展变式 | 1200 | 24% | 覆盖 benchmark 全部模板，防"背题" |
| L4 OOD/对抗 | benchmark ood/adversarial 分类 + 程序化扰动（参数量级/单位/问法反转） | 360 | 14% | 泛化与抗性 |
| L5 人工精修 | 数学家/教研 1-2 人复核 L2-L3 抽样 20% + 全部 DPO 偏好对 | 700（复核） | 12% | 质量闸门 |

**SFT 合计 ~4000 条；DPO 偏好对 ~1500 对**（从 SFT 集派生，见 2.4）。规模判断依据：任务本质是**格式纪律 + 公式模板映射**，不是知识注入——数千条高一致样本即可建立行为，10 万级反而引入噪声。参照：每题型 ≥200 条 SFT（8 题型 × 200 = 1600 下限），命名一致性示范占每个样本 100%。

### 2.2 规则合成器设计（L2 核心，2-3 人日开发）

```
输入: 题型模板库 (train_bridge_bank.json scenarios=134 + formula_cheatsheet=20)
     + 参数采样空间 (每题型的 {变量名: (label, unit, min, max, step)})
输出: {question, thinking, dsl} 三元组 — dsl 由代码从同一变量表渲染
```

**一致性保证的关键设计**（直击 E1）：

```python
# 生成器伪代码 — 变量表是唯一事实源 (SSoT)
vars_table = {"L_bridge": ("桥长", 800, "m"), "L_train": ("车长", 200, "m"),
              "v_train": ("速度", 20, "m/s")}
pipeline = [
    {"formula": "L_bridge+L_train",
     "eval": "params.L_bridge+params.L_train", ...},   # ← 从 vars_table 渲染, 不可能漂移
    {"formula": "results[1]/v_train",
     "eval": "results[1]/params.v_train", ...},
]
assert all(eval 引用的名字 ⊆ vars_table.keys())      # 生成时硬校验, 0 漂移
```

命名规范固化进生成器（同时写进 system prompt）：英文蛇形/驼峰禁中文、语义前缀（L_=长度 v_=速度 n_=数量 t_=时间）、禁单字母、禁数字引用。thinking 段由模板生成"提取参数→列公式→核对键名→输出"四步推理文本，**键名核对步骤显式出现在每个样本的 thinking 里**——这是对 E1 最强的行为示范。

### 2.3 SFT 语料格式（bnup-prep 现成管线）

```jsonl
{"instruction": "一列长200米的火车以20米/秒的速度通过800米大桥，求通过时间。",
 "input": "",
 "system": "<BNUP system prompt: 角色+DSL schema+命名规范+标签纪律>",
 "output": "<thinking>\n1. 提取参数: 桥长→L_bridge=800m, 车长→L_train=200m, 速度→v_train=20m/s\n2. 公式: 总路程=L_bridge+L_train; 时间=总路程/v_train\n3. 核对: eval 引用 L_bridge/L_train/v_train — 与 parameters 键名逐字一致 ✓\n4. 验算: 1000/20=50\n</thinking>\n<dsl>\n{...完整 DSL JSON, eval 全部引用已定义键名...}\n</dsl>"}
```

处理命令：`ft bnup-prep --sft --input raw_4000.json --output sft_v1.jsonl`（内置字段校验+跳过无效）。

### 2.4 DPO 偏好对构造（直击 E1 的监督信号）

chosen = SFT 正确样本；rejected 从现有负样本工厂生成，**新增第 6 类破坏器 `make_param_drift`**（本方案 1 人日）：

| rejected 类型 | 构造方式 | 针对 |
|---------------|----------|------|
| **param_drift**（新增） | 把 chosen eval 里的某个键名替换为：中文同义词（`每排`）/缩写（`cols`）/字面量（`31`）——**从真实 E1 失败样本中提取替换词表** | E1（10 例头号瓶颈） |
| broken_json | 截断尾部括号 | E5 |
| direct_answer | 跳过 thinking 直接给答案 | P2 标签纪律 |
| wrong_visual_type | 换非法 visual_type | schema |
| missing_tag | 剥离标签 | P2 |
| format_drift | 顶层字段改名 | E6 |

配对策略：每条 chosen 配 2-3 个 rejected（param_drift 出现在 ≥60% 的对里——头号错误配最高对比密度）；用 `ft bnup-prep --dpo` 输出 `{conversations, chosen, rejected}`。**DPO 的价值在这类任务上非常明确：SFT 教会"正确长什么样"，DPO 教会"差半步也是错"——param_drift 正是那种 SFT 难以靠正例穷尽的近邻错误空间。**

### 2.5 清洗与质检（1 人日）

1. **生成时硬校验**（合成器内置）：JSON 可解析 / jsonschema 校验通过 / eval 引用 ⊆ parameters 键 / SymPy 复算 eval 终值 == ground_truth（复用 `eval_harness` 求值器）——四道闸全过才入库
2. 人工抽样：L2/L3 各抽 20% 人工复核 thinking 推理自然度（防模板腔过拟合）
3. 去重：question 归一化哈希去重；参数值分布检查（每题型均匀覆盖 min/max/边界值如 0 棵树/整除 vs 余数）
4. 数据集版本化：`fusion_trainer/dataset/versioning.py` 已有机制，冻结为 `bnup-sft-v1` / `bnup-dpo-v1`

### 2.6 数据工作量小结

| 项 | 人日 |
|----|------|
| 规则合成器开发（8 题型模板+SSoT 渲染+四道闸） | 2-3 |
| make_param_drift 负样本类 + 真实失败词表提取 | 1 |
| L3 课标扩展批处理脚本 | 1 |
| 人工复核（700 条，教研 1 人） | 2 |
| **合计** | **6-7 人日** |

---

## 3. 训练执行（Stage 1 SFT → Stage 2 DPO，双路径）

### 3.0 路径选择

| 路径 | 用途 | 说明 |
|------|------|------|
| **A: fusion-mlx 主管线**（本方案默认） | 32B QLoRA SFT + DPO，M5 128GB 本机 | `ft bnup-train` 一键编排（fusion-trainer→mlx admin API），adapter 产出直接 in-place serve，零迁移 |
| B: LlamaFactory 备选 | 需要全参微调/更大模型/多 GPU 时 | 数据格式兼容（ShareGPT/Alpaca），见 3.6 |

> 决策依据：任务为格式纪律+模板映射，QLoRA r16 容量足够（10^7 可训练参数 vs 任务表面 10^4 级别模式数）；全参数微调 32B 在单机 128GB 不可行且有过拟合格式外泛化损伤风险。**若 Phase 3 评估显示 QLoRA 欠拟合（合成集 loss 降但 eval_exec 仍 <90%），先升 rank 至 32/64，再考虑路径 B。**

### 3.1 Stage 0 — 环境与基线冻结（0.5 人日）

```bash
# 1. 服务健康
curl -s http://127.0.0.1:11434/api/health
# 2. 基座就位: mlx-community/Qwen2.5-32B-Instruct-4bit (~18GB) 预热加载一次
curl -X POST http://127.0.0.1:11434/admin/api/models/load -d '{"model_id": "Qwen2.5-32B-Instruct-4bit"}'
# 3. 冻结评估基线 (e2e_28final.json 已有; 360 题全量基线补跑一次存档)
python scripts/e2e_bnup_eval.py --direct-mlx --model <base> --full --output e2e_baseline_full.json
# 4. 数据集入库 + 版本冻结
ft bnup-prep --sft --input data/bnup/raw_4000.json --output data/bnup/sft_v1.jsonl
ft bnup-prep --dpo --input data/bnup/sft_v1.jsonl --output data/bnup/dpo_v1.jsonl --negatives 3
```

### 3.2 Stage 1 — SFT（QLoRA-8bit，配置 `configs/bnup_sft_32b.yaml`）

**超参**（yaml 已按 spec 落定，关键项及理由）：

| 参数 | 值 | 理由 |
|------|-----|------|
| method | qlora, quant_bits=8 | 32B 上可训的量化底座（spec 的 QDoRA 近似，mlx 无 dora+quantize 组合路径） |
| lora_rank / alpha | 16 / 32.0 | 格式任务容量够；alpha=2×rank 标准配比 |
| lora_target_modules | q/k/v/o_proj | 注意力层为主，JSON 结构任务无需 MLP |
| learning_rate | 1e-4 | QLoRA 标准区间 1e-4~2e-4；**格式纪律任务宁小勿大**（大 lr 易过拟合模板腔、伤通用能力） |
| num_epochs | 3 | 4000 条 ×3 = 12k steps@eff_bs16；第 2 epoch 末通常收敛，第 3 观察过拟合 |
| max_seq_length | 4096 | **防 JSON 截断（E5）**——最长样本（复杂几何题 6 步 pipeline）实测 <3.5k |
| batch_size × grad_accum | 2 × 8 = eff 16 | 128GB 显存约束下的最大有效批量 |
| lr_scheduler / warmup | cosine / 100 steps (≈0.1 ratio) | 标准 |

**执行**（两种等价方式）：

```bash
# 方式一: fusion-trainer 一键编排 (推荐 — 自动推送给 mlx job queue)
ft bnup-train --stage sft --config configs/bnup_sft_32b.yaml \
  --model Qwen2.5-32B-Instruct-4bit --data data/bnup/sft_v1.jsonl

# 方式二: 直发 mlx admin API (SSE 看进度)
curl -X POST http://127.0.0.1:11434/admin/api/fine-tune/jobs -d '{
  "model_id": "Qwen2.5-32B-Instruct-4bit",
  "dataset": "/absolute/path/data/bnup/sft_v1.jsonl",
  "adapter_name": "bnup-sft-v1",
  "config": {"fine_tune_type": "qlora", "quant_bits": 8,
             "lora_rank": 16, "lora_alpha": 32.0,
             "learning_rate": 1e-4, "batch_size": 2,
             "iters": 750, "max_seq_length": 4096}
}'
curl -N http://127.0.0.1:11434/admin/api/fine-tune/jobs/{job_id}/stream   # SSE 实时 loss
```

**训练监控看什么**（SSE 流 + `~/.fusion-mlx/logs/server.log`）：

| 信号 | 健康区间 | 异常处置 |
|------|----------|----------|
| train loss | 3 epoch 内平滑降至 <0.35（格式任务收敛快） | 震荡 → lr 减半；不降 → 查数据格式 |
| grad_norm | <1.0（max_grad_norm 已 clip） | 频繁 clip → lr 过大 |
| epoch 2→3 loss 差 | <0.02 | 过拟合 → 用 epoch 2 checkpoint |
| iters 估算 | 4000×3÷(2×8) ≈ 750 | 32B QLoRA 本机约 4-8h（M5 128GB） |

**产出**: adapter `bnup-sft-v1`（~200MB LoRA 权重）。**立即中评**（不等到 DPO）：

```bash
# adapter 挂上推理 (in-place swap, 不复制底座)
curl -X POST http://127.0.0.1:11434/admin/api/fine-tune/adapters/Qwen2.5-32B-Instruct-4bit/bnup-sft-v1/serve
python scripts/e2e_bnup_eval.py --direct-mlx --adapter bnup-sft-v1 --output e2e_sft_v1.json
```

**SFT 中评 gate**: eval_exec_rate ≥85%、schema_rate ≥95%、json_rate 100% 才进 DPO；eval_exec <70% → 回数据工程（合成器模板覆盖不足），不做 DPO 硬补。

### 3.3 Stage 2 — DPO（偏好对齐，配置 `configs/bnup_dpo_32b.yaml`）

**超参**：

| 参数 | 值 | 理由 |
|------|-----|------|
| beta | 0.1 | spec 指定 sigmoid loss 标准 β；小 β 更贴 chosen 但易 reward hacking，0.1 为均衡点 |
| init_adapter_path | **bnup-sft-v1**（管线自动回填 #1149） | DPO 策略模型加载 SFT adapter 续训；reference model 保持纯 base（防 reference 被 SFT 污染后 margin 失真） |
| learning_rate | 5e-6 | DPO 比 SFT 低 20 倍 — 高 lr 直接崩 alignment |
| num_epochs | 2 | 1500 对 ×2；DPO 过拟合表现为 chosen/rejected margin 暴涨但生成质量降 |
| batch_size × grad_accum | 1 × 16 = eff 16 | 偏好对是 (prompt+chosen+rejected) 三段序列，显存翻倍，bs 只能 1 |
| max_seq_length | 4096 | 同 SFT |

```bash
ft bnup-train --stage dpo --config configs/bnup_dpo_32b.yaml \
  --adapter-path <sft_v1_adapter_path> --data data/bnup/dpo_v1.jsonl
# 或直发: POST /admin/api/fine-tune/dpo/jobs {"model_id": ..., "dataset": ..., 
#          "adapter_name": "bnup-dpo-v1", "config": {"beta": 0.1, "init_adapter_path": ...}}
```

**DPO 专属监控**：

| 信号 | 健康区间 | 异常处置 |
|------|----------|----------|
| reward_margin | 持续为正且缓升 | 暴涨（>5σ）→ reward hacking，降 lr 或减 epoch |
| acc_chosen | 0.65-0.85 | >0.95 = 数据太容易（rejected 太假），需更近邻的 param_drift 负例 |
| 生成质量抽查 | 每 50 iters 手测 3 题 | margin 涨但 DSL 变差 → 立即停，用前 checkpoint |

**产出**: adapter `bnup-dpo-v1`（= BNUP-Final 候选）。

### 3.4 Merge 与命名（0.5 人日）

```bash
# 两段 adapter 链式合并入底座 → 产出最终可分发权重 (fusion_trainer/merge.py)
ft merge --model Qwen2.5-32B-Instruct-4bit \
  --adapters bnup-sft-v1,bnup-dpo-v1 --output Qwen2.5-32B-BNUP-Final
# 量化回 4bit 供 mlx serve
ft merge --quantize 4 --output Qwen2.5-32B-BNUP-Final-4bit
```

### 3.5 常见坑与规避（spec 避坑指南 + 本项目实测）

| 坑 | 规避 |
|-----|------|
| JSON 被截断 → E5 类错误 | max_seq_length=4096 起步；数据预处理时丢掉 >3900 token 样本而非截断 |
| lora_layers 过多 → 显存爆 | 只挂 q/k/v/o_proj 16 层；报 OOM 时先降 batch 再降 layers |
| DPO reference 被 SFT 污染 | init_adapter 只给 policy；reference 保持 base-only（管线已处理，勿手改） |
| adapter 直接改底座目录 | 用 in-place swap（#389）——每 adapter 独立底座副本会吃 18GB×N 显存 |
| macOS 睡眠中断训练 | `caffeinate -dis` 包裹训练命令；job queue 断点由 checkpoint 恢复 |
| 中文键名回流 | 合成器 hard-block 中文键；DPO param_drift 负例强化惩罚 |

### 3.6 路径 B：LlamaFactory 备选（何时用、怎么对齐）

**触发条件**（任一）：① QLoRA r64 仍欠拟合 ② 决定上 32B 全参（需 ≥8×A100/H100 云 GPU）③ 需要多任务混合训练（BNUP + 未来语文学科）

```bash
# 数据格式转换: 本管线 JSONL 与 LlamaFactory sharegpt 格式同构, 只需字段映射
# {"instruction","input","output","system"} → {"conversations":[{from:human/gpt,...}],"system":...}
llamafactory-cli train examples/train_lora/bnup_sft.yaml   # 同超参移植
llamafactory-cli train examples/train_lora/bnup_dpo.yaml   # stage: dpo, pref_beta: 0.1
# 产出 merged 模型 → 转 MLX: 
mlx_lm.convert --hf-path <merged-dir> -q --q-bits 4   # 回 mlx 生态 serve
```

对齐要点：学习率换算（LlamaFactory 按全局 batch 归一，等效 lr 同为 1e-4/5e-6）、chat_template 必须与 mlx 侧一致（Qwen2.5 模板）、GBNF 无对应（依赖同样的人工重试防线）。**估 2-3 人日额外工作**，非必要不走。

---

## 4. 评估体系（训练闭环的验收闸门）

### 4.1 三级评估瀑布

| 级 | 集 | 工具 | 通过标准 | 频率 |
|----|-----|------|----------|------|
| L-a 训练中 | 合成集留出 5%（200 条不参与训练） | SSE loss + 留出集 loss | 留出 loss 同步下降（与训练集差 <0.1） | 每 save_every |
| L-b 冒烟 | 28 题 E2E（PRD 口径） | `e2e_bnup_eval.py --direct-mlx --adapter <name>` | 五项全达标 | SFT 中评 / DPO 后 / merge 后各一次 |
| L-c 全量 | 360 题基准（in_domain 216/ood 72/adv 72） | 同上 `--full` | §1.2 gate 表 | merge 后最终验收 |

### 4.2 逐指标归因联动（关键：评估要能回指训练数据）

| 指标不达标 | 优先归因 | 数据侧对策 |
|------------|----------|------------|
| eval_exec_rate 低 | E1 命名漂移仍在 | ① 查失败样本 drift 词表 → 补 param_drift 负例 ② 合成器加"更易漂移"的变量名变体（缩写/复数/大小写扰动）再生成 |
| schema_rate 低 | 字段缺失/类型错 | 补 format_drift 负例权重；检查对应题型模板 |
| math_accuracy 低但 eval_exec 高 | 公式选择错（E3） | 该题型 SFT 加量 2×；misconception（125 条）反例进 DPO |
| ood 低 in_domain 高 | 过拟合模板腔 | 数据增强：题面改写（同构异述）/参数位置打乱；降 epoch 至 2 |
| adversarial 低 | 对抗抗性 | L4 对抗集加量；thinking 里加"陷阱识别"步骤示范 |

### 4.3 回归防线

- 每 epoch checkpoint 保存（`save_every: 50`）；最终 adapter 与最佳 checkpoint 都要过 28 题冒烟，取优者进 DPO
- 通用能力抽检（防格式过拟合伤基座）：10 题通用数学/常识问答人工评分，merge 后对比基座不下降超过 1 档
- 全部评估产物按 `e2e_<stage>_<ts>.json` 存档（results 目录），可追溯对比（`compare_models.py` 已有）

---

## 5. 部署回灌（训练完怎么进生产）

### 5.1 双形态接入

| 形态 | 接入方式 |
|------|----------|
| local（macOS） | adapter 留在 fusion-mlx：`/admin/api/fine-tune/adapters/Qwen2.5-32B-Instruct-4bit/bnup-dpo-v1/serve`（in-place swap，毫秒切换）→ k12 `.env` `FUSION_MLX_MODEL=Qwen2.5-32B-Instruct-4bit` 不变，mlx 侧 adapter 常驻即生效；或 merge 成 BNUP-Final-4bit 独立模型直接指定 |
| cloud（Ubuntu） | merge 产物上传 HF/对象存储 → 云端推理服务（vLLM/SGLang）挂载 BNUP-Final；k12 侧零改动（`FUSION_MLX_URL` 指向托管端点即可） |

### 5.2 灰度与回滚

1. BNUP-Final 与基座**并行 serve**（fusion-mlx 单 base 多 adapter / 云端双端点）
2. k12 配置热更切换（`config/runtime` 改 `FUSION_MLX_MODEL` → 5s 生效免重启，#27 机制）
3. 灰度顺序：内部教师账号 → 单校 → 全量；期间看门狗 + metrics（LLM 计数/延迟）对比基线
4. 回滚 = 热更文件改回原模型名，1 分钟内完成

### 5.3 数据飞轮（持续改进）

- k12 生产日志已记录 `答疑 q=... answer=N字` 级别埋点 → 增加失败样本捕获（eval exec 失败率按题型统计）
- 教师纠错界面（可选二期）：教师标记错误讲解 → 进 DPO 偏好对队列 → 季度性 v2 训练
- 版本管理：`bnup-sft-v2/dpo-v2` 迭代沿用同一管线，benchmark 只增不改（360 题为最小稳定集）

---

## 6. 时间线、工作量与风险

### 6.1 总时间线（含并行）

```
D1-D3   数据工程: 合成器开发 + param_drift 负类 + L3 扩展脚本
D3-D5   语料生成 4000 SFT + 1500 DPO 对 + 人工复核 (教研并行)
D5      Stage0: 环境基线冻结; 32B 底座下载预热
D5-D6   SFT 训练 (4-8h 机时 + 监控调优) + 中评 gate
D6-D7   DPO 训练 + 冒烟
D7      merge + 28 题冒烟 + 360 全量验收
D8      部署回灌 + 灰度
        ── 合计 ~8 个工作日 (2 人: 1 算法 + 0.5 数据 + 0.5 教研复核) ──
```

### 6.2 工作量汇总

| 阶段 | 人日 |
|------|------|
| 数据工程（§2） | 6-7 |
| 训练执行与调优（§3，含机时等待的并行人力） | 2-3 |
| 评估与部署回灌（§4-5） | 1.5 |
| 合计 | **9.5-11.5 人日**（墙钟 ~8 天） |

### 6.3 风险与缓解

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| R1 | 合成数据模板腔过拟合 → ood 掉分 | 中 | ood <75% | 题面改写增强 + epoch 降到 2 + ood 专项评估前置到 SFT 中评 |
| R2 | param_drift 负例不够"近邻"→ DPO acc_chosen 虚高 | 中 | eval_exec 改善不足 | 真实失败词表驱动负例；acc_chosen >0.95 即加难负例 |
| R3 | 32B QLoRA 显存不足/训练中断 | 低 | 进度延迟 | caffeinate + checkpoint 恢复；降 rank 16→8 保底可训 |
| R4 | 格式过拟合损伤通用能力 | 低 | 答疑体验降 | §4.3 通用抽检 gate；r16 小容量本身就是护栏 |
| R5 | 360 全量过不了但 28 过了（分布偏斜） | 中 | 返工 | L-c 提前到 SFT 中评就跑一次全量（机时允许），不等最终 |
| R6 | 训练机被日常推理任务抢占 | 中 | 机时冲突 | 训练窗口内 k12 切 cloud 形态（双形态开关已就绪），mlx 独占训练 |

### 6.4 与既有工作的衔接

- 本方案产物直接服务于 PRD A5（89% 阈值验收）：`python scripts/e2e_bnup_eval.py --direct-mlx --model Qwen2.5-32B-BNUP-Final` 重跑即验收
- 数据飞轮与 k12 现有 metrics/看门狗（#28）/配置热更（#27）/双形态开关（ff0c0fa）全部复用，无新增基础设施
- 前置条件：fusion-trainer `bnup-prep/bnup-train` 管线 issue #59 已合入；fusion-mlx DPO/ORPO #399 已运行

---

## 7. 一页执行清单（TL;DR）

1. **数据是主体**（6-7 人日）：程序化合成 4000 条 SFT——变量表 SSoT 渲染保证 parameters/eval 键名 100% 一致，thinking 里显式示范"键名核对"步骤；1500 对 DPO——新增 param_drift 负类（中文同义词/缩写/字面量替换，词表来自真实 E1 失败）
2. **SFT**（QLoRA-8bit r16 lr1e-4 3ep）：中评 gate eval_exec ≥85% 才进 DPO，否则回数据侧
3. **DPO**（β0.1 lr5e-6 2ep 链式 SFT adapter）：盯 reward_margin 与 acc_chosen 防 hacking
4. **评估三级**：留出 loss → 28 冒烟 → 360 全量；每项指标不达标都有明确的数据侧对策（§4.2）
5. **部署**：adapter in-place serve + 配置热更灰度，回滚 1 分钟
6. **总计 ~9.5-11.5 人日 / 8 个墙钟日**，基础设施零新建



