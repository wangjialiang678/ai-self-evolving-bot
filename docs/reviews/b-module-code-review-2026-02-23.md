# B 模块 Code Review（2026-02-23）

## 审查范围

- 仅审查 B 类核心模块：`core/` 目录及其对应测试、联调测试。
- 明确排除：A 类模块实现本身（`extensions/` 仅用于接口契约核对，不做实现审查）。
- 参考文档：`docs/dev/mvp-module-plan.md`、`docs/dev/mvp-dev-guide.md`。

## 执行的验证

- 静态审查：`core/` 全部文件逐行检查。
- 测试执行：
  - 命令：`.venv/bin/python -m pytest tests/test_workspace.py tests/test_config.py tests/test_llm_client.py tests/test_rules.py tests/test_memory.py tests/test_context.py tests/test_telegram.py tests/test_architect.py tests/test_bootstrap.py tests/test_agent_loop.py tests/integration/test_context_chain.py tests/integration/test_post_task_chain.py -v`
  - 结果：`202 passed`（无失败）。
- 动态复现：针对高风险路径做了最小复现实验（见各条 Finding）。

## Findings（按严重度排序）

### P0-1: `flush_queue()` 在限流/发送失败场景可能进入无限循环

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/telegram.py:406`
  - `/Users/michael/projects/AI自进化系统/core/telegram.py:294`
  - `/Users/michael/projects/AI自进化系统/core/telegram.py:333`
  - `/Users/michael/projects/AI自进化系统/core/telegram.py:437`
- 问题：
  - `flush_queue()` 直接遍历 `self._message_queue`，而 `send_message()` 在限流或异常时会再次 `_enqueue()` 到同一列表，导致遍历过程中列表持续增长。
  - 该路径几乎不发生 `await` 阻塞，`asyncio.wait_for` 也无法及时打断。
- 影响：
  - 队列刷新可导致 CPU 打满、任务卡死、消息重复入队，属于可触发的可用性故障。
- 复现：
  - 将队列放入 `proposal` 消息并把当日 `proposal` 计数置为上限，调用 `flush_queue()` 后出现持续日志 `Daily proposal limit reached, queued`，无法返回。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_telegram.py:340` 仅覆盖 flush 正常发送与 DND，不覆盖 flush 过程中的失败重入/限流重入。

### P0-2: Architect 写文件未做路径约束，存在路径逃逸（任意路径写入）风险

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/architect.py:401`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:404`
- 问题：
  - `target_path = self.workspace_path / target_rel` 直接使用提案中的相对路径，未做 `resolve()` 后的根目录约束校验。
  - 提案来源包含 LLM 输出，理论上可生成 `../outside.txt` 之类路径。
- 影响：
  - 可写出 `workspace` 外文件，属于高危安全问题（越权写文件）。
- 复现：
  - 用 `files_affected: ["../outside.txt"]` 执行提案，`workspace` 外文件被创建，且返回 `status=executed`。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_architect.py` 未覆盖非法路径拒绝场景。

### P0-3: 内容生成失败时，提案仍会被标记为 `executed`

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/architect.py:383`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:398`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:166`
- 问题：
  - `_apply_changes()` 在 `new_content` 缺失且 LLM 生成失败时只记录日志并 `return`，不抛错。
  - `execute_proposal()` 继续执行并调用 `_update_proposal_status(..., "executed")`。
- 影响：
  - 系统状态与真实文件状态不一致，后续验证/回滚逻辑会基于错误事实运行。
- 复现：
  - 使用总是抛异常的 `llm_client` 执行无 `new_content` 提案，结果 `status=executed` 且目标文件不存在。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_architect.py` 未覆盖“无 `new_content` + LLM 失败”的执行结果一致性。

### P1-1: 多文件提案只会修改第一个文件，造成“部分应用”且无告警

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/architect.py:377`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:400`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:153`
- 问题：
  - 提案可声明多个 `files_affected`（且备份也会覆盖全部），但 `_apply_changes()` 只写第一个文件。
- 影响：
  - 语义上“已执行”的提案实际只执行一部分，导致验证结果偏差、回滚语义混乱。
- 复现：
  - 两文件提案执行后，第一个文件更新，第二个文件保持旧内容，但返回仍是 `executed`。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_architect.py` 未验证多文件提案“全部生效”。

### P1-2: 自动生成 `proposal_id` 存在同日碰撞，导致历史提案被覆盖

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/architect.py:323`
  - `/Users/michael/projects/AI自进化系统/core/architect.py:338`
- 问题：
  - 缺省 ID 规则为 `prop_YYYYMMDD_{idx}`，跨多次 `analyze_and_propose()` 调用会重复。
  - `_save_proposal()` 以同名文件直接覆盖。
- 影响：
  - 历史提案记录丢失，验证链路与审计链路不可靠。
- 复现：
  - 连续两次 `analyze_and_propose()`（LLM 不返回 proposal_id）后，磁盘仅保留 1 个文件，内容被第二次覆盖。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_architect.py` 未覆盖 ID 生成幂等与去重策略。

### P1-3: Bootstrap 流程可被跳阶段直接“完成”，状态文件损坏时会直接崩溃

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/bootstrap.py:109`
  - `/Users/michael/projects/AI自进化系统/core/bootstrap.py:132`
  - `/Users/michael/projects/AI自进化系统/core/bootstrap.py:55`
- 问题：
  - `process_stage()` 未校验 `stage` 是否等于当前阶段，可直接调用 `preferences` 完成引导。
  - `_load_state()` 对 `.bootstrap_state.json` 无异常保护，损坏时抛 `JSONDecodeError`。
- 影响：
  - 引导数据完整性无法保证；坏状态文件可导致服务路径中断。
- 复现：
  - 首次直接 `process_stage("preferences", ...)` 返回 `completed=True`。
  - 写入非法 JSON 状态文件后调用 `get_current_stage()` 抛 `JSONDecodeError`。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_bootstrap.py` 未覆盖越序调用与坏状态文件恢复。

### P1-4: 主 LLM 失败时可能返回空回复给用户（无降级文案）

- 位置：
  - `/Users/michael/projects/AI自进化系统/core/llm_client.py:99`
  - `/Users/michael/projects/AI自进化系统/core/agent_loop.py:188`
  - `/Users/michael/projects/AI自进化系统/core/agent_loop.py:196`
- 问题：
  - `LLMClient.complete()` 失败返回空字符串而不是抛错。
  - `AgentLoop.process_message()` 只捕获异常，不处理空字符串结果。
- 影响：
  - 用户可能收到空白回复，且该任务仍进入后处理链，污染统计与反思。
- 复现：
  - 无 `anthropic`/无 key 环境下调用，`system_response` 长度为 0。
- 缺失测试：
  - `/Users/michael/projects/AI自进化系统/tests/test_agent_loop.py` 仅覆盖“抛异常时降级文案”，未覆盖“返回空串时降级”。

## 总体结论

- 测试面当前较广，但存在若干“测试全绿仍会在真实运行中触发”的关键风险，集中在：
  - 队列刷新可用性（P0）
  - 提案执行安全与一致性（P0/P1）
  - 状态机健壮性（P1）
- 建议优先级：先修 P0（`telegram.flush_queue`、`architect` 路径约束与执行状态一致性），再修 P1（多文件一致性、ID 去重、Bootstrap 状态机、空回复降级）。
