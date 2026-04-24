import aiohttp
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
            timeout = aiohttp.ClientTimeout(total=10.0),
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


    def __getattr__(self, name):

        async def wrapper(*args, **kwargs):
            return await self._call(name, *args, **kwargs)

        return wrapper
