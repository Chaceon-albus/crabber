import argparse
import asyncio
import json

from datetime import datetime

import bilibili_api as biliapi

from crabber.misc import jsonify


def display_reply(reply: dict, prefix: str="") -> None:
    msg = reply.get("content", {}).get("message", "")
    time = datetime.fromtimestamp(reply.get("ctime", 0))
    name = reply.get("member", {}).get("uname", "???")
    # rpid = reply.get("rpid", -1)
    print(f"{prefix}{name} 发布于 {time}：{msg}")


async def main(oid: int, type_: str, pages: int):

    with open("credential.json") as f:
        cred = json.load(f)

    credential = biliapi.Credential(**cred)

    offset = ""
    page = 0
    res_type = biliapi.comment.CommentResourceType[type_.upper()]

    while page < pages:
        page += 1

        resp = await biliapi.comment.get_comments_lazy(
            oid,
            res_type,
            offset=offset,
            credential=credential,
        )
        offset = resp.get("cursor", {}).get("pagination_reply", {}).get("next_offset", "")

        for reply in resp.get("replies", []):
            display_reply(reply)

            # if reply.get("member", {}).get("uname", "???")=="???":
            #    comment = biliapi.comment.Comment(oid, res_type, reply.get("rpid", -1), credential)
            #    sub_resp = await comment.get_sub_comments()
            #    for sub_reply in sub_resp.get("replies", []):
            #        display_reply(sub_reply, prefix="  ")

        if not offset:
            print("[INFO] no offset found, exit")
            break


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--oid", "-o", type=int, required=True)
    parser.add_argument("--type", "-t", type=str, required=True, help="CommentResourceType")
    parser.add_argument("--pages", "-p", type=int, default=5)

    args = parser.parse_args()

    asyncio.run(main(oid=args.oid, type_=args.type, pages=args.pages))
