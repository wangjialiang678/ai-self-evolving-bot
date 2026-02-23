#!/bin/bash
# 四层循环防护

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_LIB_DIR/../../agentflow/scripts/path-resolver.sh" 2>/dev/null || true
GUARD_STATE_DIR="$(resolve_path "state" 2>/dev/null || echo ".claude/agentflow/state")"

check_force_stop() {
  if [ -f /tmp/FORCE_STOP ]; then
    rm -f /tmp/FORCE_STOP
    return 0  # 应强制停止
  fi
  return 1  # 继续
}

check_max_retries() {
  local max="${1:-5}"
  local file="$GUARD_STATE_DIR/stop-retries.txt"
  mkdir -p "$GUARD_STATE_DIR"
  local count=$(cat "$file" 2>/dev/null || echo "0")
  if [ "$count" -ge "$max" ]; then
    echo "0" > "$file"
    return 0  # 已超限
  fi
  echo $((count + 1)) > "$file"
  return 1  # 未超限
}

check_timeout() {
  local timeout="${1:-300}"
  local file="$GUARD_STATE_DIR/stop-start-time.txt"
  mkdir -p "$GUARD_STATE_DIR"
  if [ -f "$file" ]; then
    local start=$(cat "$file")
    local elapsed=$(( $(date +%s) - start ))
    if [ "$elapsed" -gt "$timeout" ]; then
      rm -f "$file" "$GUARD_STATE_DIR/stop-retries.txt"
      return 0  # 已超时
    fi
  else
    date +%s > "$file"
  fi
  return 1  # 未超时
}

cleanup_guard_state() {
  rm -f "$GUARD_STATE_DIR/stop-retries.txt" "$GUARD_STATE_DIR/stop-start-time.txt"
}
