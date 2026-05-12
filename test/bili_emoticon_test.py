import argparse
import asyncio
import json

import bilibili_api as biliapi

from crabber.misc import jsonify


async def main(room_id: int, emoticon: str):

    with open("credential.json") as f:
        cred = json.load(f)

    credential = biliapi.Credential(**cred)
    room = biliapi.live.LiveRoom(room_id, credential)

    if emoticon:
        print(jsonify(await room.send_emoticon(biliapi.Danmaku(emoticon))))
    else:
        emoticons_resp = await room.get_emoticons()
        for data in emoticons_resp.get("data", []):
            print(f"{data.get('pkg_name', '')}: {data.get('pkg_descript', '')}")
            for e_item in data.get("emoticons", []):
                print(f"  {e_item.get('emoticon_unique', '')} -> {e_item.get('emoji', '')}")



if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--room", "-r", type=int, required=True)
    parser.add_argument("--emoticon", "-e", type=str, default="", help="emoticon_unique you want to send in the room, if empty, print all available emoticons")

    args = parser.parse_args()

    asyncio.run(main(room_id=args.room, emoticon=args.emoticon))
