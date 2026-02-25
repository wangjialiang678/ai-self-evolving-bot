"""evo-agent 入口 — 初始化所有模块，启动 Telegram 消息循环和定时任务。

用法:
    python main.py                  # 使用默认配置
    python main.py --config path    # 指定配置文件
    python main.py --dry-run        # 无 Telegram，仅本地测试
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, time as dt_time

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from pathlib import Path

from core.agent_loop import AgentLoop
from core.architect import ArchitectEngine
from core.bootstrap import BootstrapFlow
from core.channels.bus import MessageBus, InboundMessage, OutboundMessage
from core.channels.cron import CronService
from core.channels.heartbeat import HeartbeatService
from core.channels.manager import ChannelManager
from core.channels.telegram import TelegramInboundChannel
from core.config import EvoConfig
from core.llm_client import LLMClient
from core.telegram import TelegramChannel

logger = logging.getLogger("evo-agent")

# ──────────────────────────────────────
#  初始化
# ──────────────────────────────────────

def build_app(config: EvoConfig, workspace: Path, *, telegram_enabled: bool = True) -> dict:
    """初始化所有模块，返回模块字典。"""
    # LLM 客户端（单实例，多 Provider）
    llm = LLMClient(providers=config.providers, aliases=config.aliases)

    # Agent Loop（核心中枢）
    agent_loop = AgentLoop(
        workspace_path=str(workspace),
        llm_client=llm,
        model=config.agent_loop_model,
    )

    # Bootstrap
    bootstrap = BootstrapFlow(str(workspace))

    # Rollback Manager（供 Architect 使用）
    rollback_manager = None
    try:
        from extensions.evolution.rollback import RollbackManager
        rollback_manager = RollbackManager(str(workspace))
    except Exception as e:
        logger.warning("RollbackManager not available: %s", e)

    # MessageBus 和 ChannelManager
    bus = MessageBus()
    channel_manager = ChannelManager(bus)

    # Telegram（可选）
    telegram = None
    if telegram_enabled:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            quiet_start, quiet_end = config.quiet_hours
            telegram = TelegramChannel(
                token=token,
                chat_id=chat_id,
                dnd_start=_parse_time(quiet_start),
                dnd_end=_parse_time(quiet_end),
                queue_dir=str(workspace / "telegram_queue"),
            )

            # 新的双向入站通道
            inbound_channel = TelegramInboundChannel(
                token=token,
                allowed_chat_ids=[chat_id],
            )
            channel_manager.register(inbound_channel)
        else:
            logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, Telegram disabled")

    # Architect
    architect = ArchitectEngine(
        workspace_path=str(workspace),
        llm_client=llm,
        rollback_manager=rollback_manager,
        telegram_channel=telegram,
        model=config.architect_model,
    )

    # CronService 和 HeartbeatService（在 async_main 中配置后启动）
    cron_service = CronService()
    heartbeat_service = HeartbeatService(
        workspace=workspace,
        on_heartbeat=agent_loop.process_message,
        interval_s=config.heartbeat_interval,
    )

    return {
        "config": config,
        "workspace": workspace,
        "agent_loop": agent_loop,
        "bootstrap": bootstrap,
        "architect": architect,
        "telegram": telegram,
        "llm": llm,
        "bus": bus,
        "channel_manager": channel_manager,
        "cron_service": cron_service,
        "heartbeat_service": heartbeat_service,
    }


# ──────────────────────────────────────
#  Bootstrap 输入解析（LLM 提取结构化字段）
# ──────────────────────────────────────

_PARSE_PROMPTS = {
    "background": (
        "从用户的自然语言回复中提取以下字段，返回 JSON：\n"
        "{\"name\": \"称呼\", \"role\": \"角色\", \"experience\": \"经验等级\", "
        "\"languages\": \"常用语言\", \"focus\": \"关注方向\"}\n"
        "如果某字段缺失填空字符串。只返回 JSON，不要其他文字。"
    ),
    "projects": (
        "从用户的自然语言回复中提取以下字段，返回 JSON：\n"
        "{\"project_name\": \"项目名\", \"description\": \"描述\", "
        "\"tech_stack\": \"技术栈\", \"current_phase\": \"当前阶段\"}\n"
        "如果某字段缺失填空字符串。只返回 JSON，不要其他文字。"
    ),
    "preferences": (
        "从用户的自然语言回复中提取以下字段，返回 JSON：\n"
        "{\"response_style\": \"回复风格\", \"language\": \"语言偏好\", "
        "\"notification_level\": \"通知级别\"}\n"
        "如果某字段缺失填空字符串。只返回 JSON，不要其他文字。"
    ),
}

import json as _json

async def _parse_bootstrap_input(app: dict, stage: str, user_text: str) -> dict:
    """用 LLM 将用户自然语言解析为 Bootstrap 所需的结构化字段。"""
    from core.llm_client import LLMClient
    llm: LLMClient = app.get("llm")
    prompt = _PARSE_PROMPTS.get(stage, "")
    if not prompt or not llm:
        return {"raw_input": user_text}
    try:
        raw = await llm.complete(system_prompt=prompt, user_message=user_text, model="qwen")
        # 去掉可能的 markdown 代码块
        raw = raw.strip().strip("```json").strip("```").strip()
        return _json.loads(raw)
    except Exception as e:
        logger.warning("Bootstrap input parse failed (%s): %s", stage, e)
        return {"raw_input": user_text}


# ──────────────────────────────────────
#  Bus 桥接循环（新架构）
# ──────────────────────────────────────

async def run_bus_bridge(app: dict, stop_event: asyncio.Event):
    """Bus 桥接循环：消费 inbound 消息，路由到处理器，回复用户。"""
    bus: MessageBus = app["bus"]
    agent_loop: AgentLoop = app["agent_loop"]
    bootstrap: BootstrapFlow = app["bootstrap"]
    channel_manager: ChannelManager = app["channel_manager"]
    telegram_outbound = app["telegram"]  # 旧出站通知模块
    architect: ArchitectEngine = app["architect"]

    while not stop_event.is_set():
        try:
            msg: InboundMessage = await asyncio.wait_for(
                bus.consume_inbound(), timeout=1.0
            )
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            logger.info("Bus bridge cancelled")
            break
        except Exception as e:
            logger.error("Unexpected error consuming message: %s", e)
            continue

        tg_channel = channel_manager.get_channel("telegram")

        # --- 审批回调处理 ---
        if msg.metadata.get("callback_data"):
            callback_data = msg.metadata["callback_data"]
            if not telegram_outbound:
                logger.warning("No outbound channel for callback handling")
                continue
            try:
                result = await telegram_outbound.handle_callback(callback_data)
                if not result:
                    continue
                action = result.get("action")
                proposal_id = result.get("proposal_id")
                if not action or not proposal_id:
                    logger.error("Callback missing action/proposal_id: %s", result)
                    continue
                if action == "approve":
                    proposal = architect._load_proposal(proposal_id)
                    if proposal:
                        exec_result = await architect.execute_proposal(proposal)
                        reply = f"✅ 提案 {proposal_id} 已执行。状态: {exec_result['status']}"
                    else:
                        reply = f"❌ 找不到提案 {proposal_id}"
                elif action == "reject":
                    architect._update_proposal_status(proposal_id, "rejected")
                    reply = f"❌ 提案 {proposal_id} 已拒绝。"
                elif action == "discuss":
                    reply = f"💬 提案 {proposal_id} 标记为讨论中。请在对话中说明你的想法。"
                else:
                    reply = None
                if reply and tg_channel:
                    await tg_channel.send_message(msg.user_id, reply)
            except Exception as e:
                logger.error("Callback handling failed: %s", e)
            continue

        # --- Bootstrap 流程 ---
        if not bootstrap.is_bootstrapped():
            stage = bootstrap.get_current_stage()
            if stage == "not_started":
                bootstrap._save_state({
                    "current_stage": "background",
                    "completed_stages": [],
                    "started_at": datetime.now().isoformat(),
                    "completed_at": None,
                })
                prompt = bootstrap.get_stage_prompt("background")
                if tg_channel:
                    await tg_channel.send_message(msg.user_id, prompt)
                continue
            parsed = await _parse_bootstrap_input(app, stage, msg.text)
            result = await bootstrap.process_stage(stage, parsed)
            if tg_channel:
                await tg_channel.send_message(msg.user_id, result["prompt"])
            continue

        # --- 正常消息处理 ---
        try:
            trace = await agent_loop.process_message(msg.text)
            response = trace.get("system_response", "处理完成，但无回复内容。")
        except Exception as e:
            logger.error("process_message failed: %s", e, exc_info=True)
            response = "处理消息时出错，请稍后重试。"

        if not response or not response.strip():
            response = "处理完成，但无回复内容。"

        if tg_channel:
            for chunk in _split_message(response, 4000):
                try:
                    await tg_channel.send_message(msg.user_id, chunk)
                except Exception as e:
                    logger.error("Failed to send chunk to %s: %s", msg.user_id, e)


# ──────────────────────────────────────
#  Telegram 消息循环（已弃用）
# ──────────────────────────────────────

# DEPRECATED: 保留用于回退。新架构请使用 run_bus_bridge() + ChannelManager。
async def run_telegram_loop(app: dict):
    """Telegram 轮询循环：接收消息 → AgentLoop 处理 → 回复。"""
    telegram: TelegramChannel = app["telegram"]
    agent_loop: AgentLoop = app["agent_loop"]
    bootstrap: BootstrapFlow = app["bootstrap"]

    from telegram import Bot, Update
    from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters

    bot_app = Application.builder().token(telegram.token).build()

    async def on_message(update: Update, context):
        """处理用户文本消息。"""
        if not update.message or not update.message.text:
            return
        chat_id = update.message.chat_id
        if str(chat_id) != str(telegram.chat_id):
            return  # 只响应配置的 chat_id

        user_text = update.message.text.strip()
        logger.info("Received: %s", user_text[:100])

        # Bootstrap 检查
        if not bootstrap.is_bootstrapped():
            stage = bootstrap.get_current_stage()
            if stage == "not_started":
                # 第一次接触：发送 background 提示，标记阶段等待用户回答
                bootstrap._save_state({
                    "current_stage": "background",
                    "completed_stages": [],
                    "started_at": datetime.now().isoformat(),
                    "completed_at": None,
                })
                await update.message.reply_text(bootstrap.get_stage_prompt("background"))
                return
            # 用 LLM 将自然语言解析为结构化字段
            parsed = await _parse_bootstrap_input(app, stage, user_text)
            result = await bootstrap.process_stage(stage, parsed)
            await update.message.reply_text(result["prompt"])
            return

        # 正常消息处理
        try:
            trace = await agent_loop.process_message(user_text)
            response = trace.get("system_response", "处理完成，但无回复内容。")
        except Exception as e:
            logger.error("process_message failed: %s", e, exc_info=True)
            response = "处理消息时出错，请稍后重试。"

        # 分段发送（Telegram 限制 4096 字符）
        for chunk in _split_message(response, 4000):
            await update.message.reply_text(chunk)

    async def on_callback(update: Update, context):
        """处理审批回调（inline keyboard 按钮）。"""
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        result = await telegram.handle_callback(query.data)
        if not result:
            return

        action = result["action"]
        proposal_id = result["proposal_id"]
        architect: ArchitectEngine = app["architect"]

        if action == "approve":
            proposal = architect._load_proposal(proposal_id)
            if proposal:
                exec_result = await architect.execute_proposal(proposal)
                await query.edit_message_text(
                    f"✅ 提案 {proposal_id} 已执行。状态: {exec_result['status']}"
                )
            else:
                await query.edit_message_text(f"❌ 找不到提案 {proposal_id}")
        elif action == "reject":
            architect._update_proposal_status(proposal_id, "rejected")
            await query.edit_message_text(f"❌ 提案 {proposal_id} 已拒绝。")
        elif action == "discuss":
            await query.edit_message_text(
                f"💬 提案 {proposal_id} 标记为讨论中。请在对话中说明你的想法。"
            )

    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    bot_app.add_handler(CallbackQueryHandler(on_callback))

    logger.info("Telegram polling started")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=False)

    # 返回 bot_app 以便后续停止
    return bot_app


# ──────────────────────────────────────
#  定时任务
# ──────────────────────────────────────

# DEPRECATED: 使用 CronService + HeartbeatService 替代，见 async_main() 中的注册逻辑。
async def run_scheduler(app: dict, stop_event: asyncio.Event):
    """简易 asyncio 定时调度器。"""
    config: EvoConfig = app["config"]
    agent_loop: AgentLoop = app["agent_loop"]
    architect: ArchitectEngine = app["architect"]
    telegram: TelegramChannel | None = app["telegram"]

    observer_time = _parse_time(config.observer_schedule)   # 02:00
    architect_time = _parse_time(config.architect_schedule)  # 03:00
    briefing_time = _parse_time(
        config.get("communication.daily_report_time", "08:30")
    )

    observer_done_today = False
    architect_done_today = False
    briefing_done_today = False
    last_date = ""

    while not stop_event.is_set():
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 日期变化时重置
        if today != last_date:
            observer_done_today = False
            architect_done_today = False
            briefing_done_today = False
            last_date = today

            # 勿扰结束后 flush 队列
            if telegram:
                try:
                    await telegram.flush_queue()
                except Exception as e:
                    logger.error("Queue flush failed: %s", e)

        # Observer 深度分析 (02:00)
        if not observer_done_today and _in_window(now, observer_time, minutes=30):
            observer_done_today = True
            logger.info("Running Observer deep analysis...")
            try:
                await agent_loop.run_deep_analysis(trigger="daily")
            except Exception as e:
                logger.error("Observer deep analysis failed: %s", e)

        # Architect (03:00)
        if not architect_done_today and _in_window(now, architect_time, minutes=30):
            architect_done_today = True
            logger.info("Running Architect analysis...")
            try:
                proposals = await architect.analyze_and_propose()
                for proposal in proposals:
                    await architect.execute_proposal(proposal)
                logger.info("Architect produced %d proposals", len(proposals))
            except Exception as e:
                logger.error("Architect analysis failed: %s", e)

        # 每日简报 (08:30)
        if not briefing_done_today and _in_window(now, briefing_time, minutes=30):
            briefing_done_today = True
            if telegram:
                try:
                    summary = await agent_loop.get_daily_summary()
                    if summary:
                        tasks = summary.get("tasks", {})
                        briefing_data = {
                            "date": today,
                            "total_tasks": tasks.get("total", 0),
                            "success": tasks.get("success", 0),
                            "partial": tasks.get("partial", 0),
                            "failure": tasks.get("failure", 0),
                            "success_rate": round(tasks.get("success_rate", 0) * 100, 1),
                            "tokens_used": summary.get("tokens", {}).get("total", 0),
                        }
                        await telegram.send_daily_briefing(briefing_data)
                except Exception as e:
                    logger.error("Daily briefing failed: %s", e)

        # 每 60 秒检查一次
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
            break
        except asyncio.TimeoutError:
            pass


# ──────────────────────────────────────
#  Dry-run 模式（无 Telegram，本地交互）
# ──────────────────────────────────────

async def run_dry_mode(app: dict):
    """本地交互模式，用于测试。"""
    agent_loop: AgentLoop = app["agent_loop"]
    bootstrap: BootstrapFlow = app["bootstrap"]

    print("=== evo-agent dry-run 模式 ===")
    print("输入消息与 Agent 交互，Ctrl+C 退出\n")

    if not bootstrap.is_bootstrapped():
        print("[提示] 尚未完成 Bootstrap，首次对话将进入引导流程\n")

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit"):
            print("再见！")
            break

        if user_input == "/summary":
            summary = await agent_loop.get_daily_summary()
            print(f"Agent: {summary}\n")
            continue

        if user_input == "/deep":
            result = await agent_loop.run_deep_analysis()
            print(f"Agent: Observer 深度分析完成: {result}\n")
            continue

        trace = await agent_loop.process_message(user_input)
        response = trace.get("system_response", "(无回复)")
        print(f"Agent: {response}\n")


# ──────────────────────────────────────
#  主入口
# ──────────────────────────────────────

async def async_main(args):
    """异步主函数。"""
    # 配置
    config_path = args.config if args.config else None
    config = EvoConfig(config_path)

    # workspace
    project_root = Path(__file__).parent
    workspace = project_root / "workspace"
    workspace.mkdir(exist_ok=True)

    # 初始化
    telegram_enabled = not args.dry_run
    app = build_app(config, workspace, telegram_enabled=telegram_enabled)

    if args.dry_run:
        await run_dry_mode(app)
        return

    # 正常模式：Channel + Bus 桥接 + 定时任务
    stop_event = asyncio.Event()

    def handle_signal(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # 启动所有通道
    channel_manager: ChannelManager = app["channel_manager"]
    await channel_manager.start_all()

    # 注册 cron 定时任务
    config: EvoConfig = app["config"]
    agent_loop: AgentLoop = app["agent_loop"]
    architect: ArchitectEngine = app["architect"]
    telegram_outbound: TelegramChannel | None = app["telegram"]
    cron_service: CronService = app["cron_service"]
    heartbeat_service: HeartbeatService = app["heartbeat_service"]

    async def _observer_deep():
        logger.info("Cron: Running Observer deep analysis...")
        await agent_loop.run_deep_analysis(trigger="daily")

    async def _architect_run():
        logger.info("Cron: Running Architect analysis...")
        proposals = await architect.analyze_and_propose()
        for proposal in proposals:
            await architect.execute_proposal(proposal)
        logger.info("Cron: Architect produced %d proposals", len(proposals))

    async def _daily_briefing():
        if not telegram_outbound:
            return
        logger.info("Cron: Sending daily briefing...")
        today = datetime.now().strftime("%Y-%m-%d")
        summary = await agent_loop.get_daily_summary()
        if summary:
            tasks = summary.get("tasks", {})
            briefing_data = {
                "date": today,
                "total_tasks": tasks.get("total", 0),
                "success": tasks.get("success", 0),
                "partial": tasks.get("partial", 0),
                "failure": tasks.get("failure", 0),
                "success_rate": round(tasks.get("success_rate", 0) * 100, 1),
                "tokens_used": summary.get("tokens", {}).get("total", 0),
            }
            await telegram_outbound.send_daily_briefing(briefing_data)

    cron_service.register("observer_deep", config.observer_cron, _observer_deep)
    cron_service.register("architect_run", config.architect_cron, _architect_run)
    cron_service.register("daily_briefing", config.briefing_cron, _daily_briefing)

    # Bus 桥接循环
    bridge_task = asyncio.create_task(run_bus_bridge(app, stop_event))

    # 启动 CronService 和 HeartbeatService
    await cron_service.start()
    await heartbeat_service.start()

    logger.info("evo-agent is running. Press Ctrl+C to stop.")

    # 等待停止信号
    await stop_event.wait()

    # 清理：先取消 task，等待其完成，再停止通道
    bridge_task.cancel()
    try:
        await asyncio.gather(bridge_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    await cron_service.stop()
    await heartbeat_service.stop()
    await channel_manager.stop_all()
    logger.info("evo-agent stopped.")


def main():
    parser = argparse.ArgumentParser(description="evo-agent: self-evolving AI agent")
    parser.add_argument("--config", type=str, help="Path to evo_config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Local interactive mode (no Telegram)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asyncio.run(async_main(args))


# ──────────────────────────────────────
#  工具函数
# ──────────────────────────────────────

def _parse_time(s: str) -> dt_time:
    """解析 "HH:MM" 为 datetime.time。"""
    try:
        parts = s.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return dt_time(2, 0)


def _in_window(now: datetime, target: dt_time, minutes: int = 30) -> bool:
    """检查当前时间是否在 target ± minutes/2 的窗口内。"""
    target_dt = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    delta = abs((now - target_dt).total_seconds())
    return delta < minutes * 60 / 2


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """将长消息分段。"""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # 在 max_len 附近找换行符
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


if __name__ == "__main__":
    main()
