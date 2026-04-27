import aiohttp
import logging

from .interface import BaseService


class NtfyService(BaseService):


    def __init__(self, config: dict, logger: logging.Logger) -> None:
        super().__init__()

        self.logger = logger
        self.endpoint: str = config.get("endpoint", "").rstrip("/")

        headers = {}
        if (token := config.get("token", "")):
            headers.update({"Authorization": f"Bearer {token}"})

        if not self.endpoint:
            self.logger.warning("ntfy service endpoint not configured")

        self.client = aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10.0),
        )


    async def send_notify(self, topic: str, title: str, message: str, priority: int = 3, attach: str = "", actions: list = []) -> None:

        if not self.endpoint:
            self.logger.warning("ntfy service endpoint not configured, skipping notify")
            return

        if not topic:
            self.logger.warning("ntfy topic not configured, skipping notify")
            return

        payload = {
            "topic": topic,
            "priority": priority,
            "title": title,
            "message": message,
        }

        if attach:
            payload["attach"] = attach

        if actions:
            payload["actions"] = actions

        try:
            async with self.client.post(self.endpoint, json=payload) as resp:
                resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"ntfy service failed to send notification: {e}")
