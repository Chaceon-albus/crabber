import json
import signal
import threading

from crabber.logging import logger


def jsonify(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def wait_for_shutdown() -> None:
    shutdown_event = threading.Event()

    def signal_handler(signum, _):
        logger.info(f"received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    shutdown_event.wait()


def coin_to_cny(coin: int|float, rate: float = 0.001) -> float:
    return coin * rate