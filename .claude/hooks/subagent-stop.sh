#!/bin/bash
# 子代理完成追踪
set -euo pipefail

# 读取输入（用 read -t 防止 stdin 无数据时阻塞）
INPUT=""
while IFS= read -r -t 5 line; do
  INPUT="${INPUT}${line}"
done
: "${INPUT:='{}'}"
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // "unknown"' 2>/dev/null || echo "unknown")
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "unknown"' 2>/dev/null || echo "unknown")

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/../agentflow/scripts/path-resolver.sh" 2>/dev/null || true
RESULTS_DIR="$(resolve_path "results" 2>/dev/null || echo ".claude/agentflow/results")"
COMPLETIONS_FILE="$RESULTS_DIR/completions.jsonl"
LOCK_DIR="$RESULTS_DIR/completions.lock.d"

mkdir -p "$RESULTS_DIR"

# 使用 jq 安全构建 JSON，mkdir 原子锁防止并发写入交错
RECORD=$(jq -n \
  --arg id "$AGENT_ID" \
  --arg type "$AGENT_TYPE" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{agent_id:$id, agent_type:$type, completed_at:$ts}')

# 带超时的锁
_lock_wait=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  sleep 0.1
  _lock_wait=$((_lock_wait + 1))
  if [ "$_lock_wait" -gt 50 ]; then
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" 2>/dev/null || true
    break
  fi
done
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

echo "$RECORD" >> "$COMPLETIONS_FILE"

exit 0
