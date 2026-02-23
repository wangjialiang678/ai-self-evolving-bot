#!/bin/bash
# 状态管理函数

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_LIB_DIR/../../agentflow/scripts/path-resolver.sh" 2>/dev/null || true
STATE_DIR="$(resolve_path "state" 2>/dev/null || echo ".claude/agentflow/state")"

get_workflow_state() {
  local file="$STATE_DIR/workflow-state.json"
  if [ -f "$file" ]; then
    cat "$file"
  else
    echo '{"active":false}'
  fi
}

is_workflow_active() {
  local state=$(get_workflow_state)
  local active=$(echo "$state" | jq -r '.active // false')
  [ "$active" = "true" ]
}

get_pending_stages() {
  local state=$(get_workflow_state)
  echo "$state" | jq -r '(.pending_stages // []) | length'
}

get_current_stage() {
  local state=$(get_workflow_state)
  echo "$state" | jq -r '.current_stage // "none"'
}

count_pending_tasks() {
  local pool="$(resolve_file "tasks/task-pool.json" 2>/dev/null || echo ".claude/agentflow/tasks/task-pool.json")"
  if [ -f "$pool" ]; then
    jq '[.tasks[] | select(.status == "pending" or .status == "claimed")] | length' "$pool" 2>/dev/null || echo "0"
  else
    echo "0"
  fi
}

count_incomplete_todos() {
  local plan="$(resolve_file "plans/current-plan.md" 2>/dev/null || echo ".claude/agentflow/plans/current-plan.md")"
  if [ -f "$plan" ]; then
    grep -c '^\- \[ \]' "$plan" 2>/dev/null || echo "0"
  else
    echo "0"
  fi
}
