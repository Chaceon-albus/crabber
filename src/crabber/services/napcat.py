import aiohttp
import asyncio
import logging

from crabber.misc import jsonify

from .interface import BaseService


class NapCatService(BaseService):

    def __init__(self, config: dict, logger: logging.Logger) -> None:
        super().__init__()

        self.logger = logger
        self.endpoint: str = config["endpoint"].rstrip("/")

        headers = {"Content-Type": "application/json"}

        if (token:=config.get("token", "")):
            headers.update({"Authorization": f"Bearer {token}"})
        else:
            logger.info("napcat token not configured, please make sure the napcat instance is secured")

        # services are initialized under async Crabber._bootstrap(...),
        # so it is safe to create a ClientSession here
        self.client = aiohttp.ClientSession(
            headers = headers,
            # napcat may need to download many images before sending
            # make timeout longer to wait
            timeout = aiohttp.ClientTimeout(total=60.0),
        )


    async def _call(self, action: str, *args, **kwargs) -> dict:

        url = f"{self.endpoint}/{action}"

        aiohttp_reserved_keys = {"params", "headers", "timeout", "proxy", "ssl"}
        request_options = {k: kwargs.pop(k) for k in aiohttp_reserved_keys if k in kwargs}

        json_payload = args[0] if args and isinstance(args[0], dict) else kwargs
        json_payload = {k: v for k, v in json_payload.items() if v is not None}

        resp_json = {}

        try:
            async with self.client.post(url, json=json_payload, **request_options) as resp:
                resp.raise_for_status()
                resp_json = await resp.json()
        except aiohttp.ClientResponseError as e:
            err_msg = f"NapCat API call failed: {action} -> [{e.status}] {e.message}"
            if resp_json: err_msg += f"\n{jsonify(resp_json)}"
            self.logger.error(f"NapCat API call failed: {action} -> {e}")
            raise
        except Exception as e:
            err_msg = f"NapCat API call failed: {action} -> {e}"
            if resp_json: err_msg += f"\n{jsonify(resp_json)}"
            self.logger.error(f"NapCat API call failed: {action} -> {e}")
            raise
        else:
            return resp_json


    async def send_msg_concurrently(self, content: str | list, groups: list, users: list) -> None:
        try:

            group_tasks = [self.send_msg(
                message_type="group",
                group_id=f"{gid}",
                message=content,
            ) for gid in groups]

            private_tasks = [self.send_msg(
                message_type="private",
                user_id=f"{uid}",
                message=content,
            ) for uid in users]

            results = await asyncio.gather(*group_tasks, *private_tasks, return_exceptions=True)
            all_ids = groups + users

            for k, res in enumerate(results):
                if isinstance(res, Exception):
                    self.logger.error(f"failed to send to {all_ids[k]}: {res}")

        except Exception as e:
            self.logger.error(f"failed to send msg: {e}")
        else:
            self.logger.debug(f"message = {content}")


    async def send_msg_sequentially(self, content: str | list, groups: list, users: list, cooldown: int=2) -> None:

        for gid in groups:
            try:
                await self.send_msg(
                    message_type="group",
                    group_id=f"{gid}",
                    message=content,
                )
                await asyncio.sleep(cooldown)
            except Exception as e:
                self.logger.error(f"failed to send msg to group {gid}: {e}")

        for uid in users:
            try:
                await self.send_msg(
                    message_type="group",
                    group_id=f"{uid}",
                    message=content,
                )
                await asyncio.sleep(cooldown)
            except Exception as e:
                self.logger.error(f"failed to send msg to user {uid}: {e}")


    def __getattr__(self, name):

        async def wrapper(*args, **kwargs):
            return await self._call(name, *args, **kwargs)

        return wrapper
