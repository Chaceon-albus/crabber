import asyncio
import logging

from typing import ClassVar, Any, cast

from openai import DefaultAioHttpClient
from openai import AsyncOpenAI

from .interface import BaseService


class LlmService(BaseService):

    service_name: ClassVar[str] = "llm"

    def __init__(self, config: dict, logger: logging.Logger) -> None:
        super().__init__()
        self.config = config
        self.logger = logger
        self.provider = config.get("provider", "openai")
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url")
        self.chat_params = config.get("chat_params", {})

        if self.provider == "openai":
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=DefaultAioHttpClient(),
            )
            self.logger.info("llm service initialized successfully with openai provider")
        else:
            self.client = None
            self.logger.warning(f"unknown llm provider: {self.provider}")

    def new_chat(self, system_prompt: str | list[str] | None = None) -> "LlmChat":
        if self.provider != "openai" or not self.client:
            raise ValueError(f"llm provider {self.provider} is not configured or unsupported")

        return LlmChat(
            client=self.client,
            chat_params=self.chat_params,
            logger=self.logger,
            system_prompt=system_prompt,
        )

    async def close(self) -> None:
        if self.client:
            self.logger.info("closing llm service client...")
            await self.client.close()


class LlmChat:

    def __init__(
        self,
        client: AsyncOpenAI,
        chat_params: dict,
        logger: logging.Logger,
        system_prompt: str | list[str] | None = None,
    ) -> None:
        self._client = client
        self._chat_params = chat_params
        self._logger = logger
        self.history: list[dict[str, Any]] = []

        if system_prompt is not None:
            if isinstance(system_prompt, str):
                self.history.append({"role": "system", "content": system_prompt})
            elif isinstance(system_prompt, list):
                for prompt in system_prompt:
                    self.history.append({"role": "system", "content": str(prompt)})
            else:
                self.history.append({"role": "system", "content": str(system_prompt)})

    async def send_message(self, message: str) -> str:
        """Send a message to the model and get a reply.

        Saves the message and the reply in the chat history.
        """
        self.history.append({"role": "user", "content": message})

        try:
            model = self._chat_params.get("model", "gpt-4o-mini")
            extra_params = {k: v for k, v in self._chat_params.items() if k != "model"}

            response = await self._client.chat.completions.create(
                model=model,
                messages=cast(Any, self.history),
                **extra_params,
            )

            reply = response.choices[0].message.content or ""
            self.history.append({"role": "assistant", "content": reply})

            self._logger.debug(f"llm response received successfully: {reply[:60]}...")
            return reply

        except Exception as e:
            self._logger.error(f"failed to send message to llm: {e}")
            if self.history and self.history[-1]["role"] == "user":
                self.history.pop()
            raise
