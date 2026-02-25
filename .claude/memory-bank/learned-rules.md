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

### learned-20260223150922
- tool: Bash
  action: allow
  pattern: ^git\ rm
  reason: 用户总是批准 git rm 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 3 次，拒绝 0 次

### learned-20260223160547
- tool: Bash
  action: allow
  pattern: ^cd
  reason: 用户总是批准 cd 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 4 次，拒绝 0 次

### learned-20260223161059
- tool: Bash
  action: allow
  pattern: ^git\ add
  reason: 用户总是批准 git add 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 3 次，拒绝 0 次

### learned-20260223161903
- tool: Bash
  action: allow
  pattern: ^\.venv/bin/pytest
  reason: 用户总是批准 .venv/bin/pytest 命令
  confidence: 1.0
  learned_at: 2026-02-23
  based_on: 批准 4 次，拒绝 0 次

### learned-20260224004553
- tool: Bash
  action: allow
  pattern: ^pkill
  reason: 用户总是批准 pkill 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224005439
- tool: Bash
  action: allow
  pattern: ^sleep
  reason: 用户总是批准 sleep 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224194353
- tool: Bash
  action: allow
  pattern: ^\#
  reason: 用户总是批准 # 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224202907
- tool: Bash
  action: allow
  pattern: ^git\ \-C
  reason: 用户总是批准 git -C 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 6 次，拒绝 0 次

### learned-20260224211224
- tool: Bash
  action: allow
  pattern: ^kill
  reason: 用户总是批准 kill 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224211224
- tool: Bash
  action: allow
  pattern: ^ps
  reason: 用户总是批准 ps 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224224116
- tool: Bash
  action: allow
  pattern: ^/Users/michael/projects/AI自进化系统/\.venv/bin/pytest
  reason: 用户总是批准 /Users/michael/projects/AI自进化系统/.venv/bin/pytest 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224225304
- tool: Bash
  action: allow
  pattern: ^git\ commit
  reason: 用户总是批准 git commit 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224233324
- tool: Bash
  action: allow
  pattern: ^\.venv/bin/python
  reason: 用户总是批准 .venv/bin/python 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224234809
- tool: Bash
  action: allow
  pattern: ^lsof
  reason: 用户总是批准 lsof 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 4 次，拒绝 0 次

### learned-20260224234859
- tool: Bash
  action: allow
  pattern: ^curl
  reason: 用户总是批准 curl 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 3 次，拒绝 0 次

### learned-20260224235808
- tool: Bash
  action: allow
  pattern: ^nohup
  reason: 用户总是批准 nohup 命令
  confidence: 1.0
  learned_at: 2026-02-24
  based_on: 批准 4 次，拒绝 0 次

### learned-20260225001909
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002413
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002413
- tool: Bash
  action: allow
  pattern: ^gh
  reason: 用户总是批准 gh 命令
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002424
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002430
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002437
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002443
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002450
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002458
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002508
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002522
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225002548
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225083751
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225083758
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225083803
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225083809
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225084741
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085341
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085450
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085500
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085503
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085506
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085510
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085513
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085519
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085523
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085526
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085529
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085531
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085535
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085540
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085543
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085549
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085554
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085602
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085608
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085648
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085802
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085855
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085907
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085924
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085932
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225085946
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225090013
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次

### learned-20260225090626
- tool: ToolSearch
  action: allow
  reason: 从用户行为学习
  confidence: 1.0
  learned_at: 2026-02-25
  based_on: 批准 3 次，拒绝 0 次
