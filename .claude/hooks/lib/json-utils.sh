#!/bin/bash
# JSON 工具函数

json_get() {
  echo "$1" | jq -r ".$2 // empty"
}

json_get_default() {
  echo "$1" | jq -r ".$2 // \"$3\""
}

json_block_decision() {
  local reason="$1"
  jq -n --arg reason "$reason" '{"decision":"block","reason":$reason}'
}
