import logging


class NapCatService:
    def __init__(self,config: dict, logger: logging.Logger) -> None: ...
    async def send_private_msg(self, user_id: str, message: str | list[dict]) -> dict: ...
    async def send_msg(self, message_type: str, message: str | list[dict], group_id: str | None = None, user_id: str | None = None) -> dict: ...
    # {
    #     "status": "ok",
    #     "retcode": 0,
    #     "data": { "message_id": 123456789 },
    #     "message": "",
    #     "wording": "",
    #     "echo": "tlasdasdjhj",
    #     "stream": "normal-action"
    # }
    async def send_msg_concurrently(self, content: str | list, groups: list, users: list) -> None: ...
    async def send_msg_sequentially(self, content: str | list, groups: list, users: list, cooldown: int=2) -> None: ...
