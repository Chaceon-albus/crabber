import logging
import os

from logging.handlers import RotatingFileHandler


choices = ["info", "warning", "debug"]
logger = logging.getLogger("crabber")

handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        fmt="[%(levelname)-4.4s][%(asctime)s] %(name)s - %(module)s@L%(lineno)d->%(funcName)s(): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
)

logger.addHandler(handler)


def set_level(level: str) -> None:
    logger.setLevel(logging.getLevelNamesMapping()[level.upper()] if isinstance(level, str) else level)


def configure_logging(log_file: str = "", screen_output: bool = True) -> None:

    if not screen_output:
        for h in logger.handlers[:]:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler):
                logger.removeHandler(h)

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=20*1024*1024, backupCount=5, encoding="utf-8"
        )

        file_handler.setFormatter(handler.formatter)
        logger.addHandler(file_handler)


logger.set_level = set_level # type: ignore