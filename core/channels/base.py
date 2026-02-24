"""Base channel interface for chat platforms."""

import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.channels.bus import MessageBus

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Slack, etc.) should implement this interface
    to integrate with the message bus.
    """

    name: str = "base"

    def __init__(self) -> None:
        self.bus: "MessageBus | None" = None
        self._running = False

    def set_bus(self, bus: "MessageBus") -> None:
        """Set the message bus before starting the channel."""
        if self._running:
            raise RuntimeError(f"Cannot change bus for {self.name} while it is running")
        self.bus = bus

    @abstractmethod
    async def start(self) -> None:
        """Start the channel and begin listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""

    @abstractmethod
    async def send_message(
        self,
        user_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Send a message to the given user."""

    @property
    def is_running(self) -> bool:
        """Check if the channel is currently running."""
        return self._running
