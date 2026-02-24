# 代码审核报告（2026-02-24）

## 审核范围

- 代码目录：`core/`, `extensions/`, `main.py`
- 配置与文档：`pyproject.toml`, `README.md`
- 验证方式：静态审查 + 最小复现 + 测试执行

## 执行结果

- 测试命令：`./.venv/bin/python -m pytest -q`
- 结果：`499 passed`
- 说明：系统 `python3` 为 3.9.6（不满足项目 `>=3.11`），需使用项目虚拟环境解释器。

## Findings（按严重级别排序）

### P0-1: `files_affected` 路径校验可绕过，允许写出 workspace 外

- 位置：
  - `core/architect.py:428`
  - `core/architect.py:431`
- 问题：
  - 通过 `str(target_path).startswith(str(workspace_resolved))` 做路径边界校验，存在前缀绕过（如 `workspace=/tmp/ws`，目标 `/tmp/ws2/...`）。
- 影响：
  - 可通过提案内容写入 workspace 之外的任意可写路径，属于高危越权写文件。
- 复现：
  - 最小复现已验证 `files_affected=["../ws2/pwn.md"]` 可在 workspace 外写入文件。
- 建议修复：
  - 改为 `target_path.resolve().is_relative_to(workspace_resolved)`（或 `relative_to` + `try/except`）做边界判断。

### P0-2: RollbackManager 对相对路径无约束，回滚可读写 workspace 外文件

- 位置：
  - `extensions/evolution/rollback.py:45`
  - `extensions/evolution/rollback.py:52`
  - `extensions/evolution/rollback.py:104`
  - `extensions/evolution/rollback.py:106`
  - `extensions/evolution/rollback.py:233`
  - `extensions/evolution/rollback.py:240`
- 问题：
  - `_normalize_to_workspace_relative()` 仅处理绝对路径，直接放行相对路径（如 `../ws2/secret.md`）。
  - `backup()` 和 `rollback()` 会按该路径执行复制/删除，导致跨目录读写。
- 影响：
  - 备份与回滚机制可被利用为任意文件读写通道，安全边界失效。
- 复现：
  - 最小复现已验证：可备份并回滚 workspace 外文件，且状态返回 `success`。
- 建议修复：
  - 对所有输入路径统一 `resolve()` 后强制限制在 `workspace_path` 下。
  - 元数据中的 `files` 仅存储规范化的安全相对路径（拒绝 `..` 段）。

### P1-1: `proposal_id` 未净化，提案读写路径可逃逸 `proposals/`

- 位置：
  - `core/architect.py:360`
  - `core/architect.py:372`
- 问题：
  - `_save_proposal()`/`_load_proposal()` 使用 `proposal_id` 拼接文件名且未校验。
  - 传入 `../../...` 可写入或读取 `proposals` 目录之外的 JSON 文件。
- 影响：
  - 提案存储边界被突破，可能覆盖非提案文件或读取非预期 JSON。
- 建议修复：
  - 对 `proposal_id` 做白名单校验（如 `^[A-Za-z0-9_.-]+$`）。
  - 统一走安全路径拼接函数并做目录约束。

### P1-2: Bootstrap 项目名直接参与路径拼接，存在路径穿透

- 位置：
  - `core/bootstrap.py:221`
- 问题：
  - `save_project_config(project_name, ...)` 直接把 `project_name` 作为目录名，无净化。
  - 用户输入（经 LLM 解析后）可携带 `../`，写入超出预期目录。
- 影响：
  - 可写入 `memory/projects/` 之外路径，破坏 workspace 结构。
- 建议修复：
  - 对 `project_name` 做 slug 化（仅允许安全字符）。
  - 写入前强制校验最终路径必须位于 `memory/projects` 下。

### P1-3: MemoryStore 多个写接口存在路径穿透风险

- 位置：
  - `core/memory.py:61`
  - `core/memory.py:77`
  - `core/memory.py:146`
  - `core/memory.py:161`
- 问题：
  - `key`/`project`/`conversation_id`/`date` 直接用于路径拼接并写文件，无输入约束。
- 影响：
  - 调用方一旦传入恶意标识符，可写出目标目录边界。
- 建议修复：
  - 所有标识符字段统一做格式校验与规范化。
  - 文件落盘前进行 `resolve()` + 根目录约束检查。

### P2-1: 依赖声明与实际运行依赖不一致，干净环境易运行失败

- 位置：
  - `pyproject.toml:10`
  - `core/llm_client.py:75`
  - `core/channels/cron.py:20`
- 问题：
  - 代码依赖 `openai`（Qwen 路径）和 `croniter`（CronService），但 `pyproject.toml` 未声明这两个包。
- 影响：
  - 在全新环境按 `pip install -e .` 安装后，运行到相关路径会报 `ModuleNotFoundError`。
- 建议修复：
  - 将 `openai`、`croniter` 加入项目依赖，或明确拆分为可选 extra 并在运行前校验。

### P3-1: README 运行说明与实际代码不一致

- 位置：
  - `README.md:16`
  - `README.md:74`
  - `main.py:75`
- 问题：
  - README 使用 `TELEGRAM_TOKEN`，代码读取 `TELEGRAM_BOT_TOKEN`。
  - README 声称 `280 tests passing`，与当前实际 `499 passed` 不一致。
- 影响：
  - 按文档配置时 Telegram 可能不会启用；文档可信度下降。
- 建议修复：
  - 统一环境变量命名并更新测试统计说明。

## 建议修复顺序

1. 先修复全部路径安全问题（P0/P1），并新增回归测试覆盖 `../`、绝对路径、软链接场景。
2. 修复依赖清单（P2），确保从零安装可运行。
3. 修正文档（P3），避免部署和排障误导。

