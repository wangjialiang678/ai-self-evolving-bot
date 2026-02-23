# 项目学习规则

## 学习到的规则

### learned-20260223133640
- tool: Bash
  action: allow
  pattern: ^source
  reason: 用户总是批准 source 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 6 次，拒绝 0 次

### learned-20260223140530
- tool: Bash
  action: allow
  pattern: ^ORCHESTRATE_HOME="\$\{ORCHESTRATE_HOME:\-\$HOME/projects/claude\-omo\-agentflow\}"
  reason: 用户总是批准 ORCHESTRATE_HOME="${ORCHESTRATE_HOME:-$HOME/projects/claude-omo-agentflow}" 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 6 次，拒绝 0 次

### learned-20260223143408
- tool: Bash
  action: allow
  pattern: ^mkdir
  reason: 用户总是批准 mkdir 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 3 次，拒绝 0 次

### learned-20260223143408
- tool: Bash
  action: allow
  pattern: ^mv
  reason: 用户总是批准 mv 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 3 次，拒绝 0 次

### learned-20260223144331
- tool: Bash
  action: allow
  pattern: ^python3
  reason: 用户总是批准 python3 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 3 次，拒绝 0 次
