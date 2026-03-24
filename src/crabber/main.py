import argparse
import json

from crabber.logging import logger, set_level, choices
from crabber.crabber import Crabber
from crabber.credential import CredentialManager
from crabber.misc import wait_for_shutdown


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

    crabbers: list[Crabber] = []
    bili_cm = CredentialManager(fn=args.cred, interval=config.get("credential_refresh_interval", 3600))

    for c in config.get("crabbers", []):
        crabber = Crabber(
            name=c["name"],
            room_id=c["room_id"],
            cred_manager=bili_cm,
        )

        for cmp_name in c.get("components", []):
            # do something...
            logger.info(f"registered component '{cmp_name}' to crabber '{crabber.name}'")

        crabbers.append(crabber)


    wait_for_shutdown()
    for crabber in crabbers: crabber.stop()


if __name__ == "__main__":
    pass