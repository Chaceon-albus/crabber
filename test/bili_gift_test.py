import argparse
import asyncio
import json

import bilibili_api as biliapi

# from bilibili_api.utils.network import Api as biliRawApi

from crabber.misc import jsonify


async def main(room_id: int, send: bool = False):

    with open("credential.json") as f:
        cred = json.load(f)

    credential = biliapi.Credential(**cred)
    room = biliapi.live.LiveRoom(room_id, credential)

    print(await credential.check_valid())

    gift_resp = await room.get_gift_common()

    # print(jsonify(gift_resp))

    gold_list = gift_resp.get("room_gift_list", {}).get("gold_list", [])

    popular_ticket_ids = [33988, 34391, 34003, 33987, 34003]
    popular_ticket_id = -1
    for gift in gold_list:
        if (gid:=gift.get("gift_id", -1)) in popular_ticket_ids:
            print(f"find popular ticket: id={gid}")
            popular_ticket_id = gid

    # payload = {
    #     "uid": int(credential.dedeuserid), # type: ignore
    #     "gift_id": popular_ticket_id,
    #     "gift_num": 1,
    #     "price": 100,
    #     "ruid": await room.get_ruid(), # receiver user id
    #     "send_ruid": 0,
    #     "coin_type": "gold",
    #     "bag_id": 0,
    #     "platform": "pc",
    #     "biz_code": "Live",
    #     "biz_id":room.room_display_id,
    #     "storm_beat_id": "0",
    #     "metadata": None,
    #     "receive_users": None,
    #     "live_statistics": {
    #         "pc_client": "pcWeb",
    #         "jumpfrom": "-99998",
    #         "room_category": "0",
    #         "source_event": 0,
    #         "trackid":"-99998",
    #         "official_channel": {
    #             "program_room_id":"-99998",
    #             "program_up_id":"-99998"
    #         }
    #     },
    #     "statistics": {
    #         "platform": 5,
    #         "pc_client": "pcWeb",
    #         "appId": 100
    #     },
    #     "web_location": 444.8,
    #     # "wts": int(timestamp),
    # }

    if send:
        # api = biliapi.live.API["operate"]["send_gift_gold"]
        # print(jsonify(api))
        # resp = await biliRawApi(**api, credential=room.credential).update_data(**payload).result # type: ignore
        resp = await room.send_gift_gold(
            uid=int(room.credential.dedeuserid), # type: ignore
            gift_id=popular_ticket_id, price=100,
            gift_num=1,
        )
        print(jsonify(resp)) # type: ignore

    # with open("gift_config.json", "w", encoding="utf-8") as f:
    #     f.write(jsonify(await biliapi.live.get_gift_config(room_id=room_id)))




if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--room", "-r", type=int, required=True)
    parser.add_argument("--send", "-s", action="store_true", default=False)

    args = parser.parse_args()

    asyncio.run(main(room_id=args.room, send=args.send))
