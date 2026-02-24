"""本地对话测试脚本 — 跳过 Telegram，直接与 evo-agent 交互。

用法:
    python test_chat.py           # 交互模式
    python test_chat.py --reset   # 重置 workspace（清除 Bootstrap 状态）
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 静音库日志，只保留 evo-agent 自己的
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
)
logging.getLogger("evo-agent").setLevel(logging.INFO)
logging.getLogger("core").setLevel(logging.WARNING)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))


async def handle_message(app: dict, user_text: str) -> str:
    """处理一条用户消息，返回 bot 回复文本。"""
    from core.bootstrap import BootstrapFlow
    from core.agent_loop import AgentLoop
    from main import _parse_bootstrap_input

    bootstrap: BootstrapFlow = app["bootstrap"]
    agent_loop: AgentLoop = app["agent_loop"]

    if not bootstrap.is_bootstrapped():
        stage = bootstrap.get_current_stage()
        if stage == "not_started":
            bootstrap._save_state({
                "current_stage": "background",
                "completed_stages": [],
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
            })
            return bootstrap.get_stage_prompt("background")
        parsed = await _parse_bootstrap_input(app, stage, user_text)
        result = await bootstrap.process_stage(stage, parsed)
        return result["prompt"]

    trace = await agent_loop.process_message(user_text)
    return trace.get("system_response", "（无回复）")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="重置 workspace Bootstrap 状态")
    parser.add_argument("--workspace", default="workspace", help="workspace 路径")
    args = parser.parse_args()

    workspace = Path(args.workspace)

    if args.reset:
        for f in ["USER.md", ".bootstrap_state.json"]:
            p = workspace / f
            if p.exists():
                p.unlink()
                print(f"🗑  已删除 {p}")
        print("✅ Bootstrap 状态已重置\n")

    # 初始化 app
    from main import build_app
    from core.config import EvoConfig

    config = EvoConfig()
    app = build_app(config, workspace, telegram_enabled=False)

    print("=" * 50)
    print("  evo-agent 本地测试模式")
    print("  输入消息与 Agent 交互，Ctrl+C 或输入 /quit 退出")
    print("  /reset  — 重置 Bootstrap 状态")
    print("  /status — 显示当前状态")
    print("=" * 50)
    print()

    while True:
        try:
            user_input = input("\033[36m你: \033[0m").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("再见！")
            break

        if user_input == "/reset":
            workspace = Path(args.workspace)
            for f in ["USER.md", ".bootstrap_state.json"]:
                p = workspace / f
                if p.exists():
                    p.unlink()
            print("✅ Bootstrap 状态已重置，下一条消息重新开始引导\n")
            # 重建 bootstrap
            from core.bootstrap import BootstrapFlow
            app["bootstrap"] = BootstrapFlow(workspace)
            continue

        if user_input == "/status":
            from core.bootstrap import BootstrapFlow
            bs: BootstrapFlow = app["bootstrap"]
            print(f"  bootstrapped: {bs.is_bootstrapped()}")
            print(f"  stage: {bs.get_current_stage()}")
            state_file = workspace / ".bootstrap_state.json"
            if state_file.exists():
                print(f"  state: {state_file.read_text()}")
            continue

        try:
            response = await handle_message(app, user_input)
            print(f"\033[32mBot: \033[0m{response}\n")
        except Exception as e:
            print(f"\033[31m[错误] {e}\033[0m")


if __name__ == "__main__":
    asyncio.run(main())
