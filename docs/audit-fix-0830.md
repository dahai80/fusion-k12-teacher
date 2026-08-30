# 审计修复报告 — 2026-08-30

对抗式架构审计（`~/fusion/audit/fusion-k12-teacher-audit-0830.md`，92 项缺陷，7 维度）全量修复 P0-P3。

审计结论（修复前）：**不可商用发布** — 22 项致命缺陷涉及未成年人 PII 泄露、日志泄露原始学生姓名、安全层 fail-open、认证默认关闭、敏感词分隔符绕过、提示注入未防御。

修复后：P0-P3 全部修复，303 测试全绿，ruff 干净，发布 v1.0.8。建议发布前重新审计。

## 修复统计

| 严重度 | 缺陷数 | 状态 |
|--------|--------|------|
| 阻断性 (P0 致命) | 22 | ✅ |
| 逻辑/安全 (P1) | 30 | ✅ |
| 架构/性能 (P2) | 25 | ✅ |
| 可维护性 (P3) | 15 | ✅ |
| **合计** | **92** | **✅** |

按 4 波分批修复，每波 `pytest tests/ -q` 全绿 + `ruff check .` 干净后提交。

## 修复分波

### Wave 1 — P0 致命缺陷 (22 项)

提交 `a9ed454`。

### Wave 2 — P1 逻辑/安全缺陷 (30 项)

提交 `2077f67`。

### Wave 3 — P2 架构/性能缺陷 (25 项)

提交 `3890e90`。

### Wave 4 — P3 可维护性缺陷 (15 项)

提交 `62163db`。

## 各波修复明细

### Wave 1 — P0 致命缺陷 (22 项) — `a9ed454`

修复未成年人 PII 泄露、安全层 fail-open、认证默认关闭、提示注入。

- **SEC-1**: anonymizer 日志泄露原始学生姓名 → 仅记掩码 ID
- **SEC-2**: salt 硬编码 "fusion-k12" → 显式/env/0600 密钥文件/随机生成四级解析
- **SEC-3**: hash 截断 8 hex(32bit) → 16 hex(64bit) 降碰撞
- **SEC-4**: email 无 salt 裸哈希 → keyed HMAC 带 salt
- **SEC-5**: 非字符串 PII(int 手机号)不脱敏 → str 转换后脱敏
- **SEC-6**: mask 模式同长度覆写串号 → mask 不入反匿名表
- **SEC-7**: 分隔符绕过敏感词/年龄检测 → bypass 正则
- **SEC-8**: _BYPASS_CLASS 漏 BOM, filtered_text 泄露原文 → 补 BOM
- **SEC-9**: _replace_words 短词先替换残留 → 长词优先
- **SEC-10**: check_output 无 try/except fail-open → fail-closed
- **SEC-11**: 仅年龄命中 filtered_text 保留原文 → 占位拦截
- **SRV-1**: 认证默认关闭 → fail-closed, 无 key → 403/500
- **SRV-2**: 24 个敏感端点无认证 → Depends(require_api_key)
- **ENG-1**: _parse_json 返回 None 时 UnboundLocalError → 默认值
- **ENG-2**: 4 引擎无 sanitize_input 提示注入 → 全引擎 sanitize
- **ENG-3**: from_dict 零类型强转 TypeError → 类型强转防御
- **ENG-4**: build_class_profile 统计块无 try/except → 异常隔离
- **ENG-5**: _parse_json 贪婪正则多对象返回 None → 非贪婪
- **TEST-1/2/3**: 测试单例污染/路径校验/就绪态覆盖
- 余 P0 (SRV-3 数据文件路径校验, 内容/脱敏 fail-closed 路径)

### Wave 2 — P1 逻辑/安全缺陷 (30 项) — `2077f67`

修复服务生命周期泄漏、Agent 方法白名单、CLI 退出码/类型、测试覆盖。

- **LLM-1**: close() 不关 _inner 客户端泄漏 → 一并释放
- **LLM-2**: chat retry×9 放大 → 统一重试预算
- **LLM-3**: _chat_httpx 无 KeyError 防御 → 防御+降级空串
- **LLM-4**: httpx_client 惰性初始化无锁竞态 → 加锁
- **SRV-4**: 引擎全局 None 启动中请求 500 → _ready 503
- **SRV-5**: 启动失败泄漏 scheduler/mlx → yield 前关
- **SRV-6/7/8/9/10**: 429/路径穿越/空对象/文件名泄露
- **AGT-1**: getattr 无白名单可调 __init__/close → _ALLOWED_METHODS
- **AGT-2**: data_path 任意读取 → validate_data_path 白名单
- **AGT-3/4/5/6/7/8**: JobLookupError 显式捕获/惰性锁/重建/在飞取消/超时/序列化
- **STD-1**: 前置知识点回退用 topic 匹配 ID 死逻辑 → 解析 pre_id
- **STD-2**: 单字 CJK 主题产 0 token 对齐全漏 → bigram
- **CLI-1/2/3**: join 非 str TypeError / asyncio.run 无 try 退出 0 / wordlist 写包内只读崩
- **TEST-6**: _capturing_mock prompt 断言
- 余 P1 (SRV/ENG/SEC/TEST 残余逻辑缺陷)

### Wave 3 — P2 架构/性能缺陷 (25 项) — `3890e90`

修复 CJK 匹配、schema 校验、CLI 原子写、测试覆盖缺口。

- **STD-3/4/5**: CJK bigram 整词匹配 (加法≠参加法学) — query/aligner
- **STD-6**: all_points/all_standards 返 dict 快照 (非 MappingProxyType 活视图)
- **STD-7**: CurriculumStandard.from_dict 校验 schema 版本 {1.0}
- **CLI-4/5/6**: 原子 JSON 写 (temp+os.replace, 0o600, O_NOFOLLOW) / --mode Choice / map 路径哈希避覆写
- **SEC-18**: desensitize anon 用 get_name_map() (字段已移除) 防 crash
- **TEST-4**: subject explain 仅断言成功字段
- **TEST-5**: 补 standards/analytics/agent/safety/desensitize/diff/auth 端点覆盖
- **TEST-7**: CLI run 测试断言 no-crash + 成功标记
- **TEST-8**: agent execute_step/task 测试 try/finally 防单例泄漏
- **ruff**: I001 (scheduler 导入序) / RUF019 (serve.py 冗余键检查)
- **chore**: gitignore 运行时 data/ 工件

### Wave 4 — P3 可维护性缺陷 (15 项) — `62163db`

修复脱敏加密强度、惰性锁、输入校验、死代码。

- **SEC-20**: deanonymize_name 未知 ID 静默返回原值 → 记 warning
- **SEC-21**: _mask_id_number 截断 10 hex → 全长 SHA256 (66 字符)
- **SEC-22**: _RISK_ORDER critical 死档 → 已由 Wave1 fail-closed 接线 (无需改动)
- **LLM-5**: 锁在 __init__ 绑定无循环 → _ensure_locks 惰性建
- **ENG-21**: 风险阈值小样本误报 (3 条 1 低分即报) → 要求 len>=3 且绝对>=2
- **ENG-22**: _parse_num `or 0.0` 抹掉空/零区分 → 去 or, 留 None
- **ENG-23**: setattr 无 hasattr 校验 → _set_layer 守门 (3 处)
- **STD-8**: load_all 返可变内部 dict → dict 快照
- **STD-9**: difficulty_level 不校验枚举 → {basic,standard,advanced}
- **AGT-9**: except Exception: raise 死代码 → 删除
- **AGT-10**: topics.split(",") 空段入队 → 拒空/去重
- **AGT-11**: MAX_HISTORY/MAX_CONCURRENCY 仅 import 读 → __init__ 实例属性
- **TEST-9**: 样本缺失静默 skip → fail-loud 前置校验
- **test**: test_mask_field_id_number 更新为全长 66 (SEC-21)

## 验证

| 项 | 结果 |
|----|------|
| `pytest tests/ -q` | 303 passed |
| `ruff check .` | No issues found |
| Python | 3.14.6 |
| 版本 | v1.0.8 |

## 版本

- 提交序列: `a9ed454` (P0) → `2077f67` (P1) → `3890e90` (P2) → `62163db` (P3) → `0084eb1` (bump)
- tag: `v1.0.8`
- 已推送 origin/main + v1.0.8

修复后审计结论变更: 修复前 **不可商用发布** → 修复后 P0-P3 全清, 建议发布前重新审计确认。

