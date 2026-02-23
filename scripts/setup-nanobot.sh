#!/bin/bash
# 从 .env 文件读取 API keys 并更新 NanoBot 配置
# 用法: ./scripts/setup-nanobot.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
CONFIG_FILE="$HOME/.nanobot/config.json"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ 未找到 .env 文件。请先创建:"
    echo "   cp .env.example .env"
    echo "   然后填入你的 API keys"
    exit 1
fi

# 读取 .env
source "$ENV_FILE"

if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "sk-ant-xxx" ]; then
    echo "⚠️  ANTHROPIC_API_KEY 未设置或仍为占位值"
fi
if [ -z "$GOOGLE_API_KEY" ] || [ "$GOOGLE_API_KEY" = "xxx" ]; then
    echo "⚠️  GOOGLE_API_KEY 未设置或仍为占位值"
fi
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "xxx:xxx" ]; then
    echo "⚠️  TELEGRAM_BOT_TOKEN 未设置或仍为占位值"
fi

# 创建配置目录
mkdir -p "$HOME/.nanobot"

# 生成配置（使用 python 处理 JSON）
python3 -c "
import json

config = {
    'agents': {
        'defaults': {
            'workspace': '$PROJECT_DIR/workspace',
            'model': 'anthropic/claude-sonnet-4-5',
            'maxTokens': 8192,
            'temperature': 0.7,
            'maxToolIterations': 20,
            'memoryWindow': 50
        }
    },
    'providers': {
        'anthropic': {'apiKey': '${ANTHROPIC_API_KEY:-YOUR_ANTHROPIC_API_KEY}'},
        'gemini': {'apiKey': '${GOOGLE_API_KEY:-YOUR_GOOGLE_API_KEY}'}
    },
    'channels': {
        'telegram': {
            'enabled': True,
            'token': '${TELEGRAM_BOT_TOKEN:-YOUR_TELEGRAM_BOT_TOKEN}',
            'allowFrom': [],
            'proxy': None,
            'replyToMessage': False
        }
    },
    'tools': {
        'restrictToWorkspace': False,
        'exec': {'timeout': 60},
        'web': {'maxResults': 5},
        'mcpServers': {}
    },
    'gateway': {
        'host': '0.0.0.0',
        'port': 18790
    }
}

with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
"

echo "✅ NanoBot 配置已更新: $CONFIG_FILE"
echo "   workspace: $PROJECT_DIR/workspace"
echo ""
echo "验证: nanobot status"
echo "测试: nanobot agent -m '你好'"
