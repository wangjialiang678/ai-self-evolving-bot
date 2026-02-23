#!/bin/bash
# 上下文压缩前保存状态
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/../agentflow/scripts/path-resolver.sh" 2>/dev/null || true
source "$HOOK_DIR/lib/state-manager.sh" 2>/dev/null || true

STATE_DIR="$(resolve_path "state" 2>/dev/null || echo ".claude/agentflow/state")"
mkdir -p "$STATE_DIR/snapshots"
SNAPSHOT="$STATE_DIR/snapshots/$(date +%s).json"

WF_STATE=$(get_workflow_state 2>/dev/null || echo '{"active":false}')
TASKS=$(count_pending_tasks 2>/dev/null || echo "0")
TODOS=$(count_incomplete_todos 2>/dev/null || echo "0")

# 使用 jq 安全构建 snapshot JSON
jq -n \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson wf "$WF_STATE" \
  --argjson tasks "$TASKS" \
  --argjson todos "$TODOS" \
  '{timestamp:$ts, workflow:$wf, pending_tasks:$tasks, incomplete_todos:$todos}' \
  > "$SNAPSHOT"

# 清理旧 snapshots（保留最近 20 个）
ls -1t "$STATE_DIR/snapshots"/*.json 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true

CURRENT=$(echo "$WF_STATE" | jq -r '.current_stage // "idle"' 2>/dev/null || echo "idle")
CONTEXT="工作流: $CURRENT。待处理任务: $TASKS。未完成TODO: $TODOS。"
jq -n --arg ctx "$CONTEXT" \
  '{hookSpecificOutput:{hookEventName:"PreCompact",preserveContext:$ctx}}'

exit 0
