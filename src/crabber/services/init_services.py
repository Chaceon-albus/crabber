import logging

from crabber.logging import logger as default_logger
from .interface import BaseService
from .napcat import NapCatService


async def init_services(config: list, logger: logging.Logger = default_logger) -> dict[str, BaseService]:

    services = {}

    for sc in config:
        if isinstance(sc, dict):
            match stype:=sc.get("type", ""):
                case "napcat":
                    services[stype] = NapCatService(sc.get("config", {}), logger)
                case _:
                    logger.warning(f"unknown service type {stype}")
        else:
            logger.warning(f"service config wants a dict but got {type(sc)}")

    return services
