import logging

from crabber.logging import logger as default_logger
from .interface import BaseService
from .napcat import NapCatService
from .ntfy import NtfyService
from .asr import AsrService
from .llm import LlmService


SERVICE_TYPES: dict[str, type[BaseService]] = {
    NapCatService.service_name: NapCatService,
    NtfyService.service_name: NtfyService,
    AsrService.service_name: AsrService,
    LlmService.service_name: LlmService,
}


async def init_services(config: list, logger: logging.Logger = default_logger) -> dict[str, BaseService]:

    services = {}

    for sc in config:
        if isinstance(sc, dict):
            stype = sc.get("type", "")
            service_type = SERVICE_TYPES.get(stype)

            if service_type:
                try:
                    services[stype] = service_type(sc.get("config", {}), logger)
                except Exception as e:
                    logger.error(f"failed to initialize service {stype}: {e}")
            else:
                logger.warning(f"unknown service type {stype}")
        else:
            logger.warning(f"service config wants a dict but got {type(sc)}")

    return services
