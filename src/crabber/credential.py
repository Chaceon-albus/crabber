import asyncio
import json
import os
import threading

from datetime import datetime

import bilibili_api as biliapi

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from crabber.logging import logger


class CredentialManager:

    def __init__(self, fn: str, interval: float=3600) -> None:
        self.scheduler = AsyncIOScheduler()
        self.crabbers: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}

        self.cred_file = fn
        self.has_cred = False

        if self.cred_file and os.path.isfile(self.cred_file):
            with open(self.cred_file, mode="r", encoding="utf-8") as f:
                cred_json = json.load(f)
            logger.info(f"credential file loaded from {self.cred_file}")
        else:
            cred_json = {}
            logger.info("no credential file provided or file does not exist, using empty credential")

        self.credential = biliapi.Credential(**cred_json)

        self._interval = interval
        self._lock = threading.Lock()

        if cred_json:
            self.start_monitoring()
            self.has_cred = True


    def register(self, name: str, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        with self._lock:
            self.crabbers[name] = (loop, event)


    async def _check_and_refresh(self) -> None:
        logger.info("checking credential for refresh...")
        if await self.credential.check_refresh():
            await self.credential.refresh()
            logger.info("credential refreshed")

            # save refreshed credential to the disk
            try:
                cookies = self.credential.get_cookies()

                # repeatative keys
                for key in ["SESSDATA", "DedeUserID"]:
                    if key in cookies: cookies.pop(key)

                # remove empty keys
                for k, v in list(cookies.items()):
                    if not v: cookies.pop(k)

                with open(self.cred_file, mode="w", encoding="utf-8") as f:
                    json.dump(cookies, f, indent=4, sort_keys=False, ensure_ascii=False)
            except Exception as e:
                logger.exception(f"failed to save refreshed credential: {e}")
            else:
                logger.debug(f"refreshed credential saved to {self.cred_file}")

            # notify all crabbers
            with self._lock:
                name = "unknown"
                try:
                    for name, (loop, event) in self.crabbers.items():
                        loop.call_soon_threadsafe(event.set)
                        logger.debug(f"notified credential refresh to '{name}'")
                except Exception as e:
                    logger.exception(f"{name} failed to be notified of credential refresh: {e}")


    def start_monitoring(self) -> None:
        self.scheduler.add_job(
            self._check_and_refresh,
            "interval", seconds=self._interval,
            next_run_time=datetime.now(), coalesce=True,
        )
        self.scheduler.start()
        logger.info(f"started credential monitoring with interval of {self._interval} seconds")


if __name__ == "__main__":
    pass