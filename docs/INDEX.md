# 自进化智能体系统 - 文档索引

> **最后更新**: 2026-02-25

---

## 开发文档（当前活跃）

| 文件 | 用途 |
|------|------|
| [design/v3-2-system-design.md](design/v3-2-system-design.md) | **完整系统设计** — 架构、子系统、MVP 定义。开发的设计参考 |
| [design/v3-2-scenarios.md](design/v3-2-scenarios.md) | **场景文档** — 23 个用户场景，理解系统最终体验 |
| [design/v3-3-appendix-rules-templates.md](design/v3-3-appendix-rules-templates.md) | **附录** — 规则模板、Observer/Architect 输出格式示例 |
| [dev/mvp-module-plan.md](dev/mvp-module-plan.md) | **模块划分** — A 类(Codex)/B 类(Claude) 分工、接口、验收标准 |
| [dev/mvp-dev-guide.md](dev/mvp-dev-guide.md) | **开发指南** — 接口规范(I1-I8)、测试方案、联调计划、时间线 |
| [dev/codex-tasks/](dev/codex-tasks/) | **Codex 任务包** — 提交给 Codex 的独立模块开发任务 |

---

## 历史文档（归档）

设计经历 V1 → V2 → V3 三个版本迭代，调研覆盖 EvoMaster、Evolver、NanoBot、Manus 等项目。

所有历史文档存放在 [archive/](archive/) 目录下：

| 类别 | 文件 |
|------|------|
| **V1 设计** | v1-0-origin-conversation.md, v1-1-architecture-overview.md, v1-2-subsystem-design.md, v1-3-workflows-patterns.md |
| **V2 设计** | v2-1-architecture.md, v2-2-roadmap.md, v2-3-research-topics.md |
| **V3 早期** | v3-0a-review-and-gaps.md, v3-0b-insights-mvp-rethink.md, v3-1-system-design.md, v3-2-mvp-plan.md |
| **调研** | research-evomaster-inspirations.md, research-evomaster-vs-self-evolving.md, research-evolver-pcec.md, research-nanobot.md |
| **洞察** | insight-agent-evolution-without-humans.md, insight-ai-collaboration-org-efficiency.md |
| **其他** | tech-claude-code-bridge-v2.md, ref-huyuanming-claude-code.pdf |

---

## 调研报告（2026-02）

| 文件 | 内容 |
|------|------|
| [research/pi-technical-report.md](research/pi-technical-report.md) | Pi 项目技术调研 — 最小化工具集 Agent 框架 |
| [research/bub-technical-report.md](research/bub-technical-report.md) | Bub 项目技术调研 — AI Native 自驱动 Agent |
| [research/letta-memgpt-technical-report.md](research/letta-memgpt-technical-report.md) | Letta/MemGPT 技术调研 — 分层记忆 Agent 框架 |
| [research/mem0-technical-report.md](research/mem0-technical-report.md) | Mem0 技术调研 — 外挂式 AI 记忆层 |
| [research/openclaw-article-analysis.md](research/openclaw-article-analysis.md) | 《复刻一只 OpenClaw》文章系统分析 |
| [research/openclaw-technical-report.md](research/openclaw-technical-report.md) | OpenClaw 项目技术调研 — 架构、工具、技能、安全 |
| [research/openclaw-source-deep-dive.md](research/openclaw-source-deep-dive.md) | OpenClaw 源码深度分析 — Agent Loop + 工具系统 + Telegram |
| [research/nanobot-technical-report.md](research/nanobot-technical-report.md) | Nanobot 项目技术调研 — 超轻量多平台 AI 助手 |
| [research/nanobot-source-deep-dive.md](research/nanobot-source-deep-dive.md) | Nanobot 源码深度分析 — Agent Loop + 工具系统 + Telegram |

---

## 外部项目源码（已克隆到本地）

| 项目 | 本地路径 | 说明 |
|------|----------|------|
| OpenClaw | `/Users/michael/projects/repos/openclaw/` | 通用型 AI 智能体 |
| Nanobot | `/Users/michael/projects/repos/nanobot/` | OpenClaw 最小化复现 |
| Pi | `/Users/michael/projects/repos/pi/` | 最小化工具集 Agent 框架 |
| Bub | `/Users/michael/projects/repos/bub/` | AI Native 自驱动 Agent |
| Letta | `/Users/michael/projects/repos/letta/` | MemGPT 论文产品化 |
| Mem0 | `/Users/michael/projects/repos/mem0/` | 外挂式 AI 记忆层 |

---

## 外部参考

| 目录 | 内容 |
|------|------|
| [../manus/](../manus/) | Manus 老魔架构分析、沙盒探查报告等 |
