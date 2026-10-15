# GUIDE 99 — 已知坑全集 + 故障恢复 runbook

> 适用：SFT/DPO 训练期与评测期的所有异常。按"症状 → 根因 → 处置"组织。
> 根因链完整调查记录：2026-10-14/15 训练连环中断（v8~v15，issue fusion-mlx#1205 / #1182、fusion-trainer#65）。

## A. 症状速查

| 症状 | 根因 | 处置 |
|---|---|---|
| job 状态变 `cancelled`，trainer 进程消失，checkpoint 停在某个 000N 档 | 引擎侧 memory_enforcer 超限 `fatal_exit`（见 §B1） | §B2 恢复流程 |
| `/admin/api/fine-tune/jobs/<id>` 404、jobs 清单为空 | 引擎重启，job 只存内存，持久化恢复损坏（见 §B3） | 同上，job 已丢，从零重跑 |
| 引擎 HTTP=000、`ps` 无 fusion-mlx-server | 引擎进程已死（fatal_exit 或整机重启） | `start.sh start` 拉起后重跑 |
| 整机 uptime 归零 | 15:26 型系统重启（外部因素，非本项目进程） | 同上 |
| serve 的 32B 长生成输出乱码 | TurboQuant 4-bit KV 自动开启（fusion-mlx#1230, 2026-10-16 定位） | `~/.fusion-mlx/model_settings.json` models 下加 `{"turboquant_kv_enabled": false}` 后重启；乱码期勿采信任何评测数据 |
| e2e 经 gateway 11432 卡住 | e2e runner import fusion_core 阻塞 | 用 `--direct-mlx` 直连 11434 |
| 训练 step 0/0 长期不动、trainer CPU 0% | 底座装载中（正常，~5-7 分钟）；超过 15 分钟即卡死 | 等；超时杀 trainer 重启 |

## B. 故障恢复 runbook

### B1. 根因（已确认，2026-10-14/15）

1. `memory_enforcer`（tier=custom, ceiling=120GB）连续 poll 超 ceiling → drain flip →
   `fatal_exit()` → `os._exit()` **无任何 shutdown 流程**（日志戛然而止）。
2. 触发源：共存的失控进程（卡死 runner 占 35-90GB）+ 训练自身 65-88GB 峰值。
3. 训练 job 只在进程内存 → 引擎死 = job 丢；持久化恢复本身也是坏的（§B3）。
4. 整机重启（15:26，uncleanReboot）同样杀掉一切。

### B2. 恢复流程（标准动作，按序）

```bash
# 1) 清失控进程（训练期间本机不得有大内存共存进程）
ps aux | sort -k6 -rn | head -10        # 找 RSS 异常的 python/trace 残留，确认后 kill

# 2) 引擎健康
bash ~/fusion/fusion-mlx/start.sh start  # HTTP=000 时执行；等待 200
curl -s -m 8 http://127.0.0.1:11434/ -H "Authorization: Bearer $MKEY" | head -1

# 3) 确认无 running job、无残留 trainer
ps aux | grep '[b]nup-train'
curl -s http://127.0.0.1:11434/admin/api/fine-tune/jobs \
  -H "Authorization: Bearer $MKEY" -H "X-Fusion-Route: admin" | jq '[.[]|select(.status=="running")]|length'

# 4) 记录最高 checkpoint 档（留底到 train/checkpoints/ 可选）
ls -t ~/.fusion-mlx/adapters/mlx-community--Qwen2.5-32B-Instruct-4bit/bnup_sft_32b_v2/ | head -3

# 5) 按 guides/02（或 04）重新启动训练 —— 从零重跑，job id 记入 STATUS.md
```

### B3. 已知服务端缺陷（issue 已提，落地前只能绕）

- **fusion-mlx#1205**：超限 fatal_exit 不豁免训练 job、退出前不落 checkpoint、
  persisted-jobs 恢复因 `FineTuneConfig.__init__() got an unexpected keyword` 全部失败。
- **fusion-mlx#1182**：SFT 侧 `resume_adapter_file` 硬编码 None，checkpoint 无法续训
  （DPO 侧 `init_adapter_path` 有先例，dpo_service.py:270-278）。
- **fusion-trainer#65**：无 resume、无引擎重启检测、trainer 可能变僵尸（CPU 0% 轮询死 job）。
- 缓解（在上述落地前）：训练期保持本机净空；checkpoint 每 100 步自动落盘，
  中断后手动快照 `train/checkpoints/` 留底，但**训练只能从零重跑**。

## C. 红线（每轮训练前过一遍）

1. 训练/评测期间**不向 mlx 发任何推理请求**。
2. 训练 job 必须挂长驻宿主（`bash_start`/tmux），绝不裸 shell。
3. 本机内存净空：无卡死 runner、无其他大进程。
4. 评测走 `--direct-mlx` + 引擎外直载（中评），不走 gateway / serve。
5. API key 只经环境变量，不入任何文件。
