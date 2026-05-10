from typing import ClassVar


class BaseService:

    service_name: ClassVar[str] = ""

    def __init__(self, *args, **kwargs):
        pass

    async def close(self) -> None:
        pass
