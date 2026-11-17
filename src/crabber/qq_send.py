from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING

from crabber.misc import check_exceptions
from crabber.rich_message import RichMessage, to_onebot
from crabber.services import NapCatService, QQBotService


if TYPE_CHECKING:
    from crabber.crabber import Crabber


def has_qq_service(ctx: Crabber) -> bool:
    return any(
        ctx.get_service(service_type, warn_missing=False) is not None
        for service_type in (QQBotService, NapCatService)
    )


async def send_qq_message(ctx: Crabber, message: RichMessage, groups: list | None, users: list | None) -> None:
    """Send to QQ groups / users given by their numbers.

    A target goes through the official bot when the qqbot service has an openid for it,
    otherwise through napcat. The two are separate accounts, so there is no fallback
    between them: a failed send is only logged.
    """

    groups = list(groups or [])
    users = list(users or [])

    if not groups and not users:
        return

    qqbot = ctx.get_service(QQBotService, warn_missing=False)
    napcat = ctx.get_service(NapCatService, warn_missing=False)

    bot_groups, cat_groups = [], []
    for gid in groups:
        (bot_groups if qqbot and qqbot.group_openid(gid) else cat_groups).append(gid)

    bot_users, cat_users = [], []
    for uid in users:
        (bot_users if qqbot and qqbot.user_openid(uid) else cat_users).append(uid)

    tasks = []

    if qqbot and (bot_groups or bot_users):
        tasks.append(qqbot.send_msg_concurrently(message, bot_groups, bot_users))

    if cat_groups or cat_users:
        if napcat:
            tasks.append(napcat.send_msg_concurrently(to_onebot(message), cat_groups, cat_users))
        else:
            ctx.logger.warning(f"no qq service can reach group {cat_groups} and user {cat_users}")

    results = await asyncio.gather(*tasks, return_exceptions=True)
    check_exceptions(results, msg="failed to send qq message", logger=ctx.logger)
