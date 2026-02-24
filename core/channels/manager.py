"""Channel manager for coordinating registered chat channels."""

import logging

from core.channels.base import BaseChannel
from core.channels.bus import MessageBus

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Manages a collection of BaseChannel instances tied to a single MessageBus.

    Responsibilities:
    - Register channels and wire them to the bus
    - Start / stop all channels (stop in reverse registration order)
    - Look up channels by name
    """

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus
        self._channels: list[BaseChannel] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, channel: BaseChannel) -> None:
        """Register a channel and attach it to the bus."""
        channel.set_bus(self.bus)
        self._channels.append(channel)
        logger.debug("Registered channel: %s", channel.name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Start all registered channels.

        If a channel raises during start, the error is logged and the
        remaining channels continue starting.
        """
        for channel in self._channels:
            try:
                logger.info("Starting channel: %s", channel.name)
                await channel.start()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to start channel %s: %s", channel.name, exc)

    async def stop_all(self) -> None:
        """Stop all channels in reverse registration order.

        Each channel's stop() is called independently; exceptions are
        caught so that one failure does not prevent the others from stopping.
        """
        for channel in reversed(self._channels):
            try:
                logger.info("Stopping channel: %s", channel.name)
                await channel.stop()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error stopping channel %s: %s", channel.name, exc)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_channel(self, name: str) -> BaseChannel | None:
        """Return the first registered channel with the given name, or None."""
        for channel in self._channels:
            if channel.name == name:
                return channel
        return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def channels(self) -> list[BaseChannel]:
        """Return a snapshot of the registered channel list."""
        return list(self._channels)
