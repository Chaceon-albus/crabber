import asyncio
import logging

from typing import ClassVar

import pyqbot

from crabber.rich_message import LinkButton, RichMessage, to_markdown

from .interface import BaseService


# QQ limits button text to 10 chars, and a keyboard to 5 rows
_MAX_LABEL_LEN = 10
_MAX_ROWS = 5


class QQBotService(BaseService):
    """QQ official bot via pyqbot, HTTP API only (never connects the gateway).

    Everything crabber sends is a proactive message, so each group must allow proactive
    messages. Targets are configured as QQ number -> openid, numbers without an openid
    are not reachable by the bot.
    """

    service_name: ClassVar[str] = "qqbot"

    def __init__(self, config: dict, logger: logging.Logger) -> None:
        super().__init__()

        self.logger = logger
        self.client = pyqbot.Client(
            str(config["app_id"]),
            str(config["app_secret"]),
            # the platform downloads every image in the markdown before it answers
            timeout=float(config.get("timeout", 60.0)),
        )

        self.group_openids = _openid_map(config.get("groups"), "groups", logger)
        self.user_openids = _openid_map(config.get("users"), "users", logger)

        # services are initialized under async Crabber._bootstrap(...),
        # check the configured groups in background without delaying startup
        self._check_task = asyncio.get_running_loop().create_task(self._check_groups())


    def group_openid(self, group: int | str) -> str | None:
        return self.group_openids.get(str(group))


    def user_openid(self, user: int | str) -> str | None:
        return self.user_openids.get(str(user))


    def render(self, message: RichMessage) -> tuple[str, pyqbot.Keyboard | None]:
        return to_markdown(message), self._keyboard(message.buttons)


    async def send_msg_concurrently(self, message: RichMessage, groups: list, users: list) -> tuple[list, list]:
        """Send to QQ group / user numbers, numbers without an openid are skipped.

        Returns the groups and users that the message was sent to.
        """

        markdown, keyboard = self.render(message)

        if not markdown:
            self.logger.warning("qqbot got an empty message, skipping")
            return [], []

        targets: list[tuple[str, int | str]] = []
        tasks = []

        for gid in groups:
            if (openid := self.group_openid(gid)) is None:
                self.logger.warning(f"qqbot has no openid for group {gid}, skipping")
                continue
            targets.append(("group", gid))
            tasks.append(self.client.groups.send_message(openid, markdown=markdown, keyboard=keyboard))

        for uid in users:
            if (openid := self.user_openid(uid)) is None:
                self.logger.warning(f"qqbot has no openid for user {uid}, skipping")
                continue
            targets.append(("user", uid))
            tasks.append(self.client.users.send_message(openid, markdown=markdown, keyboard=keyboard))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        sent_groups, sent_users = [], []

        for (kind, target), res in zip(targets, results):
            if isinstance(res, BaseException):
                self.logger.error(f"qqbot failed to send to {kind} {target}: {res}")
            else:
                (sent_groups if kind == "group" else sent_users).append(target)

        self.logger.debug(f"markdown = {markdown}")

        return sent_groups, sent_users


    def _keyboard(self, buttons: list[LinkButton]) -> pyqbot.Keyboard | None:

        # one button per row; links open in QQ's built-in browser
        rows: list[list[pyqbot.Button]] = [
            [pyqbot.Button.link(_label(button.label), button.url, style=pyqbot.ButtonStyle.BLUE_OUTLINE)]
            for button in buttons
        ]

        if len(rows) > _MAX_ROWS:
            self.logger.warning(f"qqbot keyboard has {len(rows)} rows, only the first {_MAX_ROWS} are sent")
            rows = rows[:_MAX_ROWS]

        return pyqbot.Keyboard.from_rows(*rows) if rows else None


    async def _check_groups(self) -> None:
        # proactive messages are rejected (40034105) unless the group allows them
        async def check(gid: str, openid: str) -> None:
            try:
                info, state = await asyncio.gather(
                    self.client.groups.get(openid),
                    self.client.groups.get_bot_state(openid),
                )
            except Exception as e:
                self.logger.warning(f"qqbot failed to check group {gid}: {e}")
                return

            if state.allow_proactive_msg is False:
                self.logger.warning(f"qqbot is not allowed to send proactive messages to group {gid} ({info.group_name})")
            else:
                self.logger.info(f"qqbot group {gid} -> {info.group_name}")

        await asyncio.gather(*(check(gid, openid) for gid, openid in self.group_openids.items()))


    async def close(self) -> None:
        if not self._check_task.done():
            self._check_task.cancel()
            await asyncio.gather(self._check_task, return_exceptions=True)
        if not self.client.is_closed:
            await self.client.close()


def _label(text: str) -> str:
    return text if len(text) <= _MAX_LABEL_LEN else text[:_MAX_LABEL_LEN - 1] + "…"


def _openid_map(raw: object, name: str, logger: logging.Logger) -> dict[str, str]:
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        logger.warning(f"qqbot {name} wants a dict of QQ number -> openid but got {type(raw).__name__}")
        return {}

    result: dict[str, str] = {}
    for number, openid in raw.items():
        if isinstance(openid, str) and openid:
            result[str(number)] = openid
        else:
            logger.warning(f"qqbot {name}: invalid openid for {number}")

    return result
