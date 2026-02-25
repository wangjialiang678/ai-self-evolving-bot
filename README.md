# 自进化智能体系统（evo-agent）

一个以规则驱动、可自我进化的 AI 对话代理。通过 Telegram 与用户交互，在后台自动观察行为、生成改进提案、验证效果，并持续优化自身的行为规则。

---

## 快速启动

```bash
# 1. 安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 配置环境变量
cp config/evo_config.yaml workspace/evo_config.yaml
export TELEGRAM_BOT_TOKEN=<your_bot_token>
export TELEGRAM_CHAT_ID=<your_chat_id>
export PROXY_API_KEY=<your_key>            # Claude Opus 4.6（通过 vtok.ai 代理）
export NVIDIA_API_KEY=<your_key>           # Qwen（辅助/低成本任务）

# 3. 运行
python main.py

# 本地调试模式（不需要 Telegram）
python main.py --dry-run
```

---

## 架构概览

```
用户 (Telegram)
    ↓
main.py               ← 入口：初始化、消息循环、定时调度
    ↓
core/agent_loop.py    ← 核心对话引擎（规则 → 上下文 → LLM → 后处理）
    ├── core/bootstrap.py     ← 首次引导（3 阶段：背景/项目/偏好）
    ├── core/architect.py     ← 进化引擎（提案 → 审批 → 执行 → 验证）
    ├── core/telegram.py      ← Telegram 消息发送（DND、队列、限流）
    ├── core/context.py       ← 上下文组装
    ├── core/llm_client.py    ← 多 Provider LLM 注册表（Claude Opus 4.6 / Qwen）
    └── core/compaction.py    ← 对话历史压缩
extensions/           ← A 类扩展模块（Observer / Signals / Reflection 等）
workspace/            ← 运行时数据（规则、记忆、提案、报告）
```

**A 类模块**（由 Codex 实现，`extensions/`）：观察者、信号生成、反思、指标、规则评分、对话压缩、轻量观察

**B 类模块**（核心框架，`core/`）：AgentLoop、Bootstrap、Architect、Telegram、Context、LLMClient、Rules、Memory、Config

---

## 定时任务

| 时间 | 任务 |
|------|------|
| 02:00 | Observer 生成每日观察报告 |
| 03:00 | Architect 分析报告、生成改进提案 |
| 08:30 | 发送每日简报给用户 |

---

## 测试

```bash
# 全量测试
python -m pytest tests/ -q

# 仅 E2E 集成测试
python -m pytest tests/integration/test_e2e.py -v
```

当前测试覆盖：**499 tests passing**

---

## 配置

主配置文件：[config/evo_config.yaml](config/evo_config.yaml)

关键配置项：

```yaml
llm:
  providers:
    opus:
      type: anthropic
      model_id: "claude-opus-4-6"
      api_key_env: "PROXY_API_KEY"
      base_url: "https://vtok.ai"
    qwen:
      type: openai
      model_id: "qwen/qwen3-235b-a22b"
      api_key_env: "NVIDIA_API_KEY"
      base_url: "https://integrate.api.nvidia.com/v1"
  aliases:
    gemini-flash: qwen
agent_loop:
  model: "opus"
observer:
  light_mode:
    enabled: true
    model: "qwen"
  deep_mode:
    schedule: "02:00"
    model: "opus"
architect:
  schedule: "03:00"
  model: "opus"
  max_daily_proposals: 3
```

---

## 文档

详见 [docs/INDEX.md](docs/INDEX.md)
