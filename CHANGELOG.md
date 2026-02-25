# Changelog

所有重要变更记录于此文件，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased]

### Changed — 多 Provider LLM 架构重构

- **`core/llm_client.py`**：重写为多 Provider 注册表架构
  - `LLMClient(providers, aliases)` 接收 provider 配置字典和别名映射
  - 支持 `anthropic` 类型（Anthropic SDK）和 `openai` 类型（OpenAI 兼容 REST API）
  - 通过 `model` 参数路由到正确的后端，支持别名解析（如 `gemini-flash` → `qwen`）
  - 客户端实例懒加载，按需创建
- **`core/config.py`**：新增 `providers`、`aliases`、`agent_loop_model` 属性，移除硬编码的模型 ID
- **`config/evo_config.yaml`**：新增 `llm.providers` 和 `llm.aliases` 配置段
- **`core/agent_loop.py`**：移除 `llm_client_light` 参数，统一使用单一 `LLMClient` 实例
- **`extensions/observer/engine.py`**：从双客户端 `(llm_client_gemini, llm_client_opus)` 改为单客户端 `(llm_client, *, light_model="qwen", deep_model="opus")`
- **`main.py`**：从 `llm_opus` + `llm_light` 双实例简化为单一 `llm` 实例
- **模型升级**：Opus 从 `claude-sonnet-4-20250514` 升级为 `claude-opus-4-6`

---

## [0.3.0] — 2026-02-23

### Added — B7 端到端集成

- **`main.py`**：系统完整入口
  - `build_app()` 初始化所有模块并返回 app 字典
  - `run_telegram_loop()` 消息轮询（python-telegram-bot v21），含 Bootstrap 路由和审批回调
  - `run_scheduler()` asyncio 定时调度（Observer 02:00、Architect 03:00、简报 08:30）
  - `run_dry_mode()` 本地交互调试模式（无需 Telegram）
  - `--dry-run` CLI 参数支持
- **`tests/integration/test_e2e.py`**：11 个 E2E 集成测试，覆盖 MVP 四大成功标准
  - 多轮对话、错误信号生成、完整 Bootstrap 流、Architect 提案执行、回滚
- **`config/evo_config.yaml`**：生产示例配置文件

### Fixed — B-core 安全与健壮性修复（来自代码审查）

- **P0 `telegram.py`**：`flush_queue()` 快照后清空队列再遍历，消除限流场景下的无限循环
- **P0 `architect.py`**：路径越界防护，`resolve()` + 根目录白名单校验，拒绝 `../` 逃逸
- **P0 `architect.py`**：内容生成失败时改为 `raise RuntimeError`（原为静默 `return`），确保 `execute_proposal` 正确标记 `failed` 而非 `executed`
- **P1 `architect.py`**：`proposal_id` 含微秒时间戳（`%H%M%S_%f`），消除同日多次调用时的文件覆盖
- **P1 `bootstrap.py`**：阶段顺序校验，禁止跳级调用（`preferences` 不可直接从 `not_started` 完成）
- **P1 `bootstrap.py`**：`_load_state()` 增加 JSON 异常保护，损坏时自动重置而非崩溃
- **P1 `agent_loop.py`**：LLM 返回空字符串时补充降级文案，用户不再收到空回复

### Tests

- `tests/test_bootstrap.py`：`TestProcessStageProjects` 和 `TestProcessStagePreferences` 更新为按正确阶段顺序调用（反映真实使用流程）

---

## [0.2.0] — 2026-02-22

### Added

- A 类模块（Codex 实现）：Observer、Signals、Reflection、Metrics、RuleScoring、Compaction、LightweightObserver
- B 类模块（核心框架）：AgentLoop、Bootstrap、Architect、Telegram、Context、LLMClient、Rules、Memory、Config、Workspace、RollbackManager
- 完整集成测试套件（context chain、post-task chain）
- Codex 任务文档（A1-A7）

---

## [0.1.0] — 2026-02-21

### Added

- 项目初始化，V3 系统设计定稿
- B 类核心模块骨架（Rules、Memory、Workspace）
- 测试基础设施（pytest + asyncio）
