#!/bin/bash
# 自动继续机制 - JSON Decision 模式 + 四层循环防护
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/../agentflow/scripts/path-resolver.sh" 2>/dev/null || true
_libs_loaded=true
for _lib in loop-guard.sh state-manager.sh json-utils.sh; do
  if [ -f "$HOOK_DIR/lib/$_lib" ]; then
    source "$HOOK_DIR/lib/$_lib"
  else
    echo "⚠️  stop hook: missing lib/$_lib — loop guards DISABLED" >&2
    echo "   Fix: ensure .claude/hooks/lib/$_lib exists" >&2
    _libs_loaded=false
  fi
done
# 库缺失时防护层无法工作，放行避免误阻塞（但已警告用户）
if [ "$_libs_loaded" = "false" ]; then
  echo "⚠️  stop hook: one or more libs missing, all guard checks skipped" >&2
  exit 0
fi

# 读取输入（用 read -t 防止 stdin 无数据时阻塞）
INPUT=""
while IFS= read -r -t 5 line; do
  INPUT="${INPUT}${line}"
done
: "${INPUT:='{}'}"
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo "false")

# === 掌天瓶模式检查：off 时直接放行 ===
MODE_FILE="$(resolve_file "state/mode.txt" 2>/dev/null || echo ".claude/agentflow/state/mode.txt")"
MODE=$(cat "$MODE_FILE" 2>/dev/null || echo "off")
if [ "$MODE" != "on" ]; then
  exit 0
fi

# === 防护层 1: stop_hook_active ===
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# === 防护层 2: 紧急退出 ===
if check_force_stop 2>/dev/null; then
  exit 0
fi

# === 防护层 3: 最大重试 ===
if check_max_retries 5 2>/dev/null; then
  exit 0
fi

# === 防护层 4: 超时 ===
if check_timeout 300 2>/dev/null; then
  exit 0
fi

# === 检查 1: 工作流状态 ===
if is_workflow_active 2>/dev/null; then
  PENDING=$(get_pending_stages 2>/dev/null || echo "0")
  CURRENT=$(get_current_stage 2>/dev/null || echo "unknown")
  if [ "$PENDING" -gt 0 ]; then
    json_block_decision "工作流进行中。当前阶段: $CURRENT，剩余 $PENDING 个阶段。请继续执行。"
    exit 0
  fi
fi

# === 检查 2: 任务池 ===
PENDING_TASKS=$(count_pending_tasks 2>/dev/null || echo "0")
if [ "$PENDING_TASKS" -gt 0 ]; then
  json_block_decision "任务池中还有 $PENDING_TASKS 个未完成任务。请继续处理。"
  exit 0
fi

# === 检查 3: 计划 TODO ===
INCOMPLETE=$(count_incomplete_todos 2>/dev/null || echo "0")
if [ "$INCOMPLETE" -gt 0 ]; then
  json_block_decision "计划中还有 $INCOMPLETE 个未完成的 TODO。请继续执行。"
  exit 0
fi

# === 全部完成 ===
cleanup_guard_state 2>/dev/null || true
exit 0
