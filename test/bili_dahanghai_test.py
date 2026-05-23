import argparse
import asyncio
import json

import bilibili_api as biliapi

# from bilibili_api.utils.network import Api as biliRawApi

from crabber.misc import jsonify


def print_item(count: int, item: dict) -> None:

    roles = ["总督", "提督", "舰长"]

    uid = item.get("uid", 0)
    ruid = item.get("ruid", 0) # receiver id
    rank = item.get("rank", 0)
    name = item.get("username", "[UNKNOWN]")
    face = item.get("face", "")
    alive = item.get("is_alive", 0),
    role = roles[item.get("guard_level", 3)-1]
    # "guard_sub_level": 0 ???

    print(f"{count:3d}, {role}, {name}, {uid}")


async def main(room_id: int) -> None:

    # with open("credential.json") as f:
    #     cred = json.load(f)

    # credential = biliapi.Credential(**cred)
    credential = None

    room = biliapi.live.LiveRoom(room_id, credential)

    # resp = await room.get_dahanghai()
    # print(jsonify(resp))

    cpage = 1
    count = 0

    while True:
        resp = await room.get_dahanghai(cpage)

        total_page = resp.get("info", {}).get("page", 1)

        if cpage == 1:
            for item in resp.get("top3", []):
                count += 1
                print_item(count, item)

        for item in resp.get("list", []):
            count += 1
            print_item(count, item)

        cpage += 1
        if cpage > total_page: break


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--room", "-r", type=int, required=True)

    args = parser.parse_args()

    asyncio.run(main(room_id=args.room))
