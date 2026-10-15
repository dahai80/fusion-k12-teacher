# GUIDE 01 — 数据工程（bnup_synth）

> 产出：`data/02-SFT/sft_v1.jsonl`（冻结）+ `data/03-DPO/dpo_v1.jsonl`（冻结）
> 脚本：`scripts/01-数据工程/bnup_synth.py`　数据卡：`materials/02-数据工程/bnup-sft-v1-dataset-card.md`

## 1. 输入与前置

- 原始语料按数据卡所述来源放置（本体不入 git，仅数据卡 + 校验和 + seed）。
- 依赖：`python3.12`，`sympy`（SymPy 数值覆写闸）。
- 先读数据卡，确认本批语料范围、年级分布、题型分布目标。

## 2. 四道闸（全部通过才入数据集）

1. **结构闸**：JSON 可解析、字段齐全（instruction/input/output 骨架）。
2. **数值闸（SymPy 覆写）**：LLM 只产题目骨架与解法文本，**所有数值由 SymPy 计算**，
   模型输出数值一律被覆写——防止 LLM 算错数污染数据。
3. **安全闸**：教基内容审（敏感词 + 年龄分层），不合格样本丢弃。
4. **去重闸**：题面 hash 去重，近似题（归一化后同 hash）只留一条。

另：**param_drift 负类**——同一题面多参数变体中，故意保留"参数漂移但答案错"的样本
作为 DPO 负类来源（教模型"换参数必须重算"）。

## 3. 执行

```bash
cd ~/fusion/fusion-k12-teacher
python3 scripts/bnup_synth.py            # 产出 data/bnup/sft_v1.jsonl + dpo_v1.jsonl
```

## 4. 冻结与校验

```bash
shasum -a 256 data/bnup/sft_v1.jsonl data/bnup/dpo_v1.jsonl
# 把校验和写进 train/SHA256SUMS.txt（README「快速使用」第 3 步）
```

冻结后**不得再改数据本体**；要改就 bump 版本号（sft_v2 …）并更新数据卡。

## 5. 产出物归档

| 产物 | 归档位置 |
|---|---|
| sft_v1.jsonl | train/data/02-SFT/ |
| dpo_v1.jsonl | train/data/03-DPO/ |
| 数据卡 | train/materials/02-数据工程/ |

## 6. 已知坑

- SymPy 覆写必须**先于**安全闸之后、去重闸之前执行（顺序错会导致去重 hash 不含真值）。
- "π 取 3.14"：题面声明近似时按 3.14 计算（benchmark gt 曾误用真 π，已修，见架构方案 §5）。
