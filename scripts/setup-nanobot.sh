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

# 检查关键 keys
if [ -z "$PROXY_API_KEY" ] || [ "$PROXY_API_KEY" = "sk-xxx" ]; then
    echo "⚠️  PROXY_API_KEY 未设置或仍为占位值"
fi
if [ -z "$NVIDIA_API_KEY" ] || [ "$NVIDIA_API_KEY" = "nvapi-xxx" ]; then
    echo "⚠️  NVIDIA_API_KEY 未设置或仍为占位值"
fi
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "xxx:xxx" ]; then
    echo "⚠️  TELEGRAM_BOT_TOKEN 未设置或仍为占位值（TG 暂禁用）"
fi

# 创建配置目录
mkdir -p "$HOME/.nanobot"

# 生成配置（使用 python 处理 JSON）
python3 -c "
import json, os

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
        'anthropic': {
            'apiKey': os.environ.get('PROXY_API_KEY', 'YOUR_PROXY_API_KEY'),
            'baseUrl': os.environ.get('PROXY_BASE_URL', 'https://vtok.ai')
        },
        'openai': {
            'apiKey': os.environ.get('NVIDIA_API_KEY', 'YOUR_NVIDIA_API_KEY'),
            'baseUrl': 'https://integrate.api.nvidia.com/v1'
        }
    },
    'channels': {
        'telegram': {
            'enabled': False,
            'token': os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN'),
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
echo "   Claude: vtok.ai 代理"
echo "   Qwen: NVIDIA 平台"
echo "   Telegram: $([ "$TELEGRAM_BOT_TOKEN" != "xxx:xxx" ] && echo '已配置' || echo '待配置')"
echo ""
echo "验证: nanobot status"
echo "测试: nanobot agent -m '你好'"
