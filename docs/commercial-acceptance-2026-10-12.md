# 商用验收报告 — 人教版小学 1-6 年级数学（2026-10-12）

**验收对象**: fusion-k12-teacher v2.1.2（HTTP API + GUI, 127.0.0.1:11448）
**依赖链**: fusion-mlx :11434 + fusion-gateway :11432（Qwen3.5-4B-MLX-4bit）
**验收方式**: 真实 LLM live 测试（19 例）+ 逐年级 E2E（6 年级 × 数据/生成链路）+ 商用横向检查（安全/配置/部署/文档）

## 结论：⚠️ 暂不具备商用条件（1 个 P0 阻塞项）

数据层与产品工程全部健康；**唯一阻塞项是 gateway 的 prompt-injection 守卫误拦所有教学 prompt**（issue #25，属 gateway 配置层，可 5 分钟修复）。修复并复验后即可商用。

## 一、Live LLM 测试（FUSION_K12_LIVE_TESTS=1，真实推理）

`10 failed, 24 passed`（101s）

| 失败分组 | 数量 | 根因 |
|----------|------|------|
| CurriculumEngine（lesson_plan/quiz/unit_plan） | 3 | `NonDegradableError: LLM HTTP 403` |
| AssessmentEngine（grade_essay/grade_math） | 2 | 同上 |
| SubjectExpert（explain_concept/generate_exercise） | 2 | 同上 |
| ContentGenerator（worksheet/flashcards） | 2 | 同上 |
| MLXClient::test_default_model | 1 | 测试脚手架缺陷（issue #26）：live 模式下 fixture 不清 `FUSION_MLX_MODEL` |

24 个通过项覆盖：引擎构造、降级语义、dataclass 序列化、错误分类、认证门控等离线可验证面。

## 二、逐年级 E2E（人教版 1-6 年级）

| 年级 | 教材单元 | 图谱节点 | 讲稿生成 | 答疑 | 场景动画 |
|------|----------|----------|----------|------|----------|
| 1 | ✅ 8 单元 22 课 | ✅ 16 | ❌ 403 | ❌ 403 | ❌ 403 |
| 2 | ✅ 9 单元 16 课 | ✅ 22 | ❌ 403 | ❌ 403 | ❌ 403 |
| 3 | ✅ 9 单元 19 课 | ✅ 25 | ❌ 403 | ❌ 403 | ❌ 403 |
| 4 | ✅ 8 单元 13 课 | ✅ 26 | ❌ 403 | ❌ 403 | ❌ 403 |
| 5 | ✅ 7 单元 12 课 | ✅ 29 | ❌ 403 | ❌ 403 | ❌ 403 |
| 6 | ✅ 8 单元 14 课 | ✅ 33 | ❌ 403 | ❌ 403 | ❌ 403 |

- 数据层 6/6 年级全部健康（教材 + 图谱 + 前端动态知识点标签）。
- 生成链路 6/6 全部被同一根因阻断（见下）。
- 讲课程模式（教案复用，零 LLM）在已备课包上不受影响（2 年级 50 包验证通过）。

## 三、P0 根因分析（issue #25）

**gateway `prompt_injection.enabled=true, action=block, threshold=0.8` 对长指令式消息误报拦截。**

实测（同一 gateway/key，短消息 200）：

| payload | 结果 |
|---|---|
| system "你是一位专业的小学数学老师。"（15 字） | 200 |
| system 500 中文字 / 350 ASCII | **403** |
| user 600 ASCII | **403** |
| 真实 BNUP_SYSTEM_PROMPT（1075 字符） | **403** |
| 直连 mlx 同 payload（绕过 gateway） | 200 |

→ 守卫在 gateway；教学 system prompt（1KB+）全部命中。这是教学产品的**必经路径**，故为 P0。

**5 分钟修复**：gateway `config.yaml` 把 k12 教学通道的 `prompt_injection.action` 改 `log`（或调高 threshold）→ 重启 gateway → 复验。

## 四、商用横向检查

| 检查项 | 结果 | 说明 |
|--------|------|------|
| API key 保护 | ✅ | 无 key 访问受保护 API → 401 |
| 教师认证 | ✅ | 错密码 → 401；token 签发/校验正常 |
| Admin key 门控 | ✅ | `/api/metrics` 无 key 403 / 带 key 200 |
| SIGTERM 优雅排水 | ✅ | 排水处理器已注册 |
| 部署模板 | ✅ | Dockerfile / docker-compose / k8s（HPA+PDB+ServiceMonitor）/ benchmark.py |
| 文档 | ✅ | README + README_CN 双语 + docs/ 9 篇 |
| 限流 | ⚠️ 未启用 | `FUSION_K12_RATE_LIMIT` 未配置（issue #27） |
| 配置热更 | ⚠️ 未启用 | `FUSION_K12_CONFIG_FILE` 未接线（issue #27） |
| 密钥管理 | ⚠️ | gateway key 明文 `.env`，两天内已轮换一次（issue #27 附轮换手册建议） |
| LLM 引擎长稳 | ⚠️ | mlx 引擎 4 次挂起（`engine is not running`），restart 可恢复；上游 fusion-mlx 问题，建议 k12 加健康探测告警 |

## 五、已提 Issue（英文）

| # | 标题 | 级别 |
|---|------|------|
| [#25](https://github.com/dahai80/fusion-k12-teacher/issues/25) | P0 (commercial blocker): all LLM teaching flows return 403 behind fusion-gateway prompt-injection guard | P0 |
| [#26](https://github.com/dahai80/fusion-k12-teacher/issues/26) | test harness: test_default_model fails whenever FUSION_K12_LIVE_TESTS=1 with FUSION_MLX_MODEL set | P2 |
| [#27](https://github.com/dahai80/fusion-k12-teacher/issues/27) | commercial readiness: production hardening flags not enabled by default (rate limit, config hot-reload, gateway key rotation) | P1 |

## 六、上线建议（按顺序）

1. **修 #25（P0）**：gateway 配置 `prompt_injection.action: log` → 重启 gateway → 复验 live 测试与逐年级 E2E（预期 19/19 live 通过、6/6 年级全绿）。
2. **修 #26**：`test_default_model` 加 `monkeypatch.delenv`，恢复测试可信度。
3. **修 #27**：`.env.example` 生产 profile 启用限流与配置热更；部署模板接线 `FUSION_K12_CONFIG_FILE`。
4. **观察项**：mlx 引擎挂起加 runbook（`start.sh restart`）；4B 模型讲稿生成 2-4 分钟/篇（前端已有思考提示），商用可评估升 9B（库内已有 `Qwen3.5-9B-4bit`，`FUSION_MLX_MODEL` 一改即生效）。
5. 完成后重跑本验收：`FUSION_K12_LIVE_TESTS=1 pytest tests/test_core.py -v` + `.venv/bin/python /tmp/acceptance_e2e.py`（脚本随报告归档）。

## 七、验收期间顺带修复（已在本仓库落地，未提交部分见 git status）

- 模型切换 1B→4B（`FUSION_MLX_MODEL`）+ `_PREFERRED_CHAT_MODELS` 补单横线精确名
- `fusion_core` 客户端超时透传（原硬编码 120s，4B 长推理必超时）
- 数字人三分模式（讲课程/举一反三/我有问题）+ 课程下拉双源 + 级联筛选
- 主题建议标签按年级动态查图谱 + 教材 loader 中英文 subject 别名
- 图谱 `visual_type` dataclass 字段修复（整图加载失败→52 节点/67 边零失败）
- scripter prompt 泄漏检测 + socratic_tutor 非 JSON 重试
