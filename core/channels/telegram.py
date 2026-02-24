"""双向 Telegram 通道 — 基于 BaseChannel 接口，通过 MessageBus 收发消息。"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from core.channels.base import BaseChannel
from core.channels.bus import InboundMessage, MessageBus

logger = logging.getLogger(__name__)


@dataclass
class TelegramChannelConfig:
    token: str
    allowed_chat_ids: list[str]
    proxy: str | None = None


class TelegramInboundChannel(BaseChannel):
    """双向 Telegram 通道。

    - 启动 python-telegram-bot long polling
    - 收到消息 / callback_query 时 publish InboundMessage 到 bus
    - 提供 send_message() 主动推送消息给用户
    """

    name = "telegram"

    def __init__(self, token: str, allowed_chat_ids: list[str], proxy: str | None = None) -> None:
        super().__init__()
        self.token = token
        self.allowed_chat_ids = [str(cid) for cid in allowed_chat_ids]
        self.proxy = proxy
        self._app = None

    # ──────────────────────────────────────
    #  生命周期
    # ──────────────────────────────────────

    async def start(self) -> None:
        """启动 long polling，注册消息处理器。"""
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            MessageHandler,
            filters,
        )

        builder = Application.builder().token(self.token)
        if self.proxy:
            builder = builder.proxy(self.proxy).get_updates_proxy(self.proxy)
        self._app = builder.build()

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        self._app.add_handler(CallbackQueryHandler(self._on_callback))

        logger.info("TelegramInboundChannel: starting polling")

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=False)
        self._running = True

    async def stop(self) -> None:
        """停止 polling，清理资源。"""
        self._running = False
        if self._app:
            logger.info("TelegramInboundChannel: stopping")
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning("Error during Telegram shutdown: %s", e)
            self._app = None

    # ──────────────────────────────────────
    #  发送
    # ──────────────────────────────────────

    async def send_message(
        self,
        user_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """通过 bot 发送消息给指定用户。

        Args:
            user_id: Telegram chat_id（字符串形式）
            text: 消息文本
            reply_markup: inline keyboard 数据（{"inline_keyboard": [[...]]})
        """
        if not self._app:
            logger.warning("TelegramInboundChannel: bot not running, cannot send")
            return

        try:
            chat_id_int = int(user_id)
        except (ValueError, TypeError):
            logger.error("Invalid user_id format: %s", user_id)
            return
        kwargs: dict[str, Any] = {"chat_id": chat_id_int, "text": text}

        if reply_markup:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            buttons = []
            for row in reply_markup.get("inline_keyboard", []):
                btn_row = []
                for btn in row:
                    if "text" not in btn:
                        logger.warning("Skipping button missing 'text' field: %s", btn)
                        continue
                    btn_row.append(InlineKeyboardButton(
                        text=btn["text"],
                        callback_data=btn.get("callback_data"),
                    ))
                if btn_row:
                    buttons.append(btn_row)
            if buttons:
                kwargs["reply_markup"] = InlineKeyboardMarkup(buttons)

        try:
            await self._app.bot.send_message(**kwargs)
        except Exception as e:
            logger.error("Failed to send Telegram message to %s: %s", user_id, e)

    # ──────────────────────────────────────
    #  内部处理器
    # ──────────────────────────────────────

    async def _on_message(self, update, context) -> None:
        """处理用户文本消息，publish 到 bus。"""
        bus = self.bus
        if not self._running or not bus:
            return
        if not update.message or not update.message.text:
            return

        chat_id = str(update.message.chat_id)
        if not self._is_allowed(chat_id):
            logger.debug("Ignoring message from disallowed chat_id: %s", chat_id)
            return

        text = update.message.text.strip()
        logger.info("Telegram message from %s: %s", chat_id, text[:80])

        await bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                user_id=chat_id,
                text=text,
                metadata={
                    "message_id": update.message.message_id,
                    "username": update.effective_user.username if update.effective_user else None,
                },
            )
        )

    async def _on_callback(self, update, context) -> None:
        """处理 inline keyboard callback_query，publish 到 bus。"""
        bus = self.bus
        if not self._running or not bus:
            return
        query = update.callback_query
        if not query or not query.data:
            return

        chat_id = str(query.message.chat_id) if query.message else None
        if not chat_id or not self._is_allowed(chat_id):
            logger.debug("Ignoring callback from disallowed chat_id: %s", chat_id)
            return

        await query.answer()
        logger.info("Telegram callback from %s: %s", chat_id, query.data)

        await bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                user_id=chat_id,
                text=query.data,
                metadata={"callback_data": query.data},
            )
        )

    # ──────────────────────────────────────
    #  工具
    # ──────────────────────────────────────

    def _is_allowed(self, chat_id: str) -> bool:
        """检查 chat_id 是否在白名单中。白名单为空时放行所有。"""
        if not self.allowed_chat_ids:
            return True
        return chat_id in self.allowed_chat_ids
