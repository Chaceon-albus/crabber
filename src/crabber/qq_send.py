from __future__ import annotations

import asyncio

from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from crabber.rich_message import RichMessage, to_onebot
from crabber.services import NapCatService, QQBotService


if TYPE_CHECKING:
    from crabber.crabber import Crabber


@dataclass(slots=True)
class QQSendResult:
    sent_groups: list = field(default_factory=list)
    sent_users: list = field(default_factory=list)
    # failed, or no qq service can reach them
    unsent_groups: list = field(default_factory=list)
    unsent_users: list = field(default_factory=list)

    @property
    def any_sent(self) -> bool:
        return bool(self.sent_groups or self.sent_users)

    @property
    def any_unsent(self) -> bool:
        return bool(self.unsent_groups or self.unsent_users)


def has_qq_service(ctx: Crabber) -> bool:
    return any(
        ctx.get_service(service_type, warn_missing=False) is not None
        for service_type in (QQBotService, NapCatService)
    )


async def send_qq_message(ctx: Crabber, message: RichMessage, groups: list | None, users: list | None) -> QQSendResult:
    """Send to QQ groups / users given by their numbers.

    A target goes through the official bot when the qqbot service has an openid for it,
    otherwise through napcat. The two are separate accounts, so there is no fallback
    between them: a failed send is only logged and reported in the result.
    """

    groups = list(groups or [])
    users = list(users or [])

    result = QQSendResult()

    if not groups and not users:
        return result

    qqbot = ctx.get_service(QQBotService, warn_missing=False)
    napcat = ctx.get_service(NapCatService, warn_missing=False)

    bot_groups, cat_groups = [], []
    for gid in groups:
        (bot_groups if qqbot and qqbot.group_openid(gid) else cat_groups).append(gid)

    bot_users, cat_users = [], []
    for uid in users:
        (bot_users if qqbot and qqbot.user_openid(uid) else cat_users).append(uid)

    # (send, its groups, its users)
    jobs: list[tuple[Awaitable[tuple[list, list]], list, list]] = []

    if qqbot and (bot_groups or bot_users):
        jobs.append((qqbot.send_msg_concurrently(message, bot_groups, bot_users), bot_groups, bot_users))

    if cat_groups or cat_users:
        if napcat:
            jobs.append((napcat.send_msg_concurrently(to_onebot(message), cat_groups, cat_users), cat_groups, cat_users))
        else:
            ctx.logger.warning(f"no qq service can reach group {cat_groups} and user {cat_users}")
            result.unsent_groups += cat_groups
            result.unsent_users += cat_users

    outcomes = await asyncio.gather(*(job for job, _, _ in jobs), return_exceptions=True)

    for (_, job_groups, job_users), outcome in zip(jobs, outcomes):
        if isinstance(outcome, BaseException):
            ctx.logger.error(f"failed to send qq message: {outcome}")
            sent_groups, sent_users = [], []
        else:
            sent_groups, sent_users = outcome

        result.sent_groups += sent_groups
        result.sent_users += sent_users
        result.unsent_groups += [gid for gid in job_groups if gid not in sent_groups]
        result.unsent_users += [uid for uid in job_users if uid not in sent_users]

    return result
