import logging

from typing import ClassVar

from .interface import BaseService


class LlmService(BaseService):

    service_name: ClassVar[str] = "llm"

    def __init__(self, config: dict, logger: logging.Logger) -> None:
        pass
