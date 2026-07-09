import argparse
import importlib
import json

from crabber.logging import logger, set_level, choices, configure_logging
from crabber.crabber import Crabber
from crabber.credential import CredentialManager
from crabber.components.safe_handler import create_safe_handler
from crabber.signal import wait_for_shutdown


def main() -> None:

    parser = argparse.ArgumentParser(
        prog="crabber",
        description="Yet another bililive stalker."
    )

    parser.add_argument("-b", "--cred", type=str, default="", help="bili credential json location")
    parser.add_argument("-c", "--conf", type=str, required=True, help="config json file location")
    parser.add_argument("-d", "--data", type=str, default="./data", help="data storage location")
    parser.add_argument("-l", "--level", type=str, choices=choices, default="info", help="logging level")

    args: argparse.Namespace = parser.parse_args()

    set_level(args.level)

    with open(args.conf, mode="r", encoding="utf-8") as f:
        config = json.load(f)

    log_file = config.get("log_file", "")
    if log_file: configure_logging(log_file=log_file, screen_output=True)

    crabbers: list[Crabber] = []
    bili_cm = CredentialManager(fn=args.cred, interval=config.get("credential_refresh_interval", 3600))


    for c in config.get("crabbers", []):

        cname = c["name"]
        crabber = Crabber(
            name=cname,
            room_id=c["room_id"],
            cred_manager=bili_cm,
            database=c.get("database", []),
            services=c.get("services", []),
            status_check_interval=config.get("status_check_interval", 120),
        )

        for component in c.get("components", []):

            cmp_name = "<unknown>"
            cmp_module_name = ""

            try:
                cmp_name = component["type"]
                cmp_config = component.get("config", {})

                cmp_module_name = f"crabber.components.{cmp_name}"
                cmp_module = importlib.import_module(cmp_module_name)
                cmp_events = component.get("events", cmp_module.default_events)

                handler = cmp_module.get_handler(
                    ctx=crabber,
                    **cmp_config,
                )

                handler = create_safe_handler(handler, cname, cmp_name)

                for event_name in cmp_events:
                    crabber.add_handler(event_name, handler)

                logger.info(f"added {cmp_name} component to {cname}")

            except ModuleNotFoundError as e:
                if e.name == cmp_module_name or cmp_module_name.startswith(f"{e.name}."):
                    logger.warning(f"unknown component type {cmp_name}")
                else:
                    logger.error(f"failed to register component {cmp_name}: {e}")
            except Exception as e:
                logger.error(f"failed to register component {cmp_name}: {e}")

        crabber.start() # just to trigger online callbacks
        crabbers.append(crabber)


    wait_for_shutdown()
    for crabber in crabbers: crabber.stop()


if __name__ == "__main__":
    pass
