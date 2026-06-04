import argparse
import asyncio
import json

import bilibili_api as biliapi

# from bilibili_api.utils.network import Api as biliRawApi

from crabber.misc import jsonify


async def main(args: argparse.Namespace):

    with open("credential.json") as f:
        cred = json.load(f)

    credential = biliapi.Credential(**cred)
    room = biliapi.live.LiveRoom(args.room, credential)

    print(await credential.check_valid())

    resp = await room.get_room_play_info_v2()

    print(jsonify(resp))





if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--room", "-r", type=int, required=True)

    args = parser.parse_args()

    asyncio.run(main(args))
