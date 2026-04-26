import asyncio
import json

from datetime import datetime

import bilibili_api as biliapi

from bilibili_api.user import User
from bilibili_api.dynamic import Dynamic

from crabber.misc import jsonify
from crabber.logging import logger
from crabber.services import init_services, NapCatService
from crabber.components.parrot import build_message_from_module


async def main():

    # with open("credential.json") as f:
    #     cred = json.load(f)

    # credential = biliapi.Credential(**cred)

    # logger.set_level("info") # type: ignore
    # logger.info("wtf?")

    # uid = input("bilibili uid: ").strip()
    # await parrot_fetch_dynamic_patched(int(uid), credential=credential)
    # return


    did = input("dynamic id: ").strip()
    info = await biliapi.dynamic.Dynamic(int(did)).get_info()
    print(jsonify(info))

    item = info.get("item", {})

    prefix = ""
    content = []
    content += build_message_from_module(item.get("modules", {}).get("module_dynamic", {}), prefix=prefix)
    content += build_message_from_module(item.get("orig", {}).get("modules", {}).get("module_dynamic", {}), prefix="\n原动态：\n")

    print(content)

    user = input("send to user via napcat: ").strip()

    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)

    services = await init_services(config["crabbers"][0]["services"])

    napcat: NapCatService = services["napcat"] # type: ignore

    resp = await napcat.send_msg(
        message_type="private",
        user_id=user,
        message=content,
    )

    print(jsonify(resp))


async def parrot_fetch_dynamic_patched(uid: int, credential: biliapi.Credential) -> None:

    try:
        resp = await User(uid, credential).get_dynamics_new()

        logger.info(jsonify(resp))

        dynamics = resp.get("items", [])

        for dynamic in dynamics:

            dn = None
            parrot_prefix = ""

            if (id_str:=dynamic.get("id_str", "")):

                # check if the dynamic has been handled before
                # if id_str in dynamic_memory: continue

                # check dynamic publish date if pub_ts exists
                if (pub_ts:=dynamic.get("modules", {}).get("module_author", {}).get("pub_ts", "")):
                    try:
                        pub_time = datetime.fromtimestamp(int(pub_ts))
                        logger.info(f"timeshift = {(datetime.now() - pub_time)}")

                        # if (datetime.now() - pub_time).total_seconds() > 1200:
                        #     # likely to be published before the program start
                        #     # since it's too long time ago, simple ignore it
                        #     # dynamic_memory[id_str] = True
                        #     logger.info(f"added dynamic {id_str} into memory")
                        #     continue

                    except Exception as e:
                        logger.error("failed to check publish date: {e}")

                # get author name
                author_name = dynamic.get("modules", {}).get("module_author", {}).get("name", "")

                try:
                    dynamic_id = int(id_str)
                except Exception as e:
                    logger.error(f"failed to convert dynamic id {id_str} into int")
                else:
                    match dynamic_type:=dynamic.get("type"):
                        case "DYNAMIC_TYPE_LIVE_RCMD":
                            # live banner?
                            pass
                        case "DYNAMIC_TYPE_AV":
                            # video
                            # dynamic["modules"]["module_dynamic"]["major"]["archive"] -> bvid, cover(http), title
                            parrot_prefix = f"{author_name}发布了视频：\n"
                            dn = Dynamic(dynamic_id, credential)
                        case "DYNAMIC_TYPE_DRAW":
                            # some general types?
                            parrot_prefix = f"{author_name}发布了动态：\n"
                            # dynamic["modules"]["module_dynamic"]["major"]["opus"]["summary"]["rich_text_nodes or text"]
                            # dynamic["modules"]["module_dynamic"]["major"]["opus"]["pics"][?]["url"](http)
                            dn = Dynamic(dynamic_id, credential)
                        case "DYNAMIC_TYPE_FORWARD":
                            # dynamic["modules"]["module_dynamic"]["desc"]["rich_text_nodes or text"]
                            # dynamic["orig"]["modules"]...
                            parrot_prefix = f"{author_name}转发了内容：\n"
                            dn = Dynamic(dynamic_id, credential)
                        case _:
                            logger.info(f"unknown dynamic type {dynamic_type}")
                            logger.debug(jsonify(dynamic))

            if dn:
                logger.info(f"{parrot_prefix}: {dn}")

    except Exception as e:
        logger.error(f"failed to fetch new dynamics: {e}")


if __name__ == "__main__":
    asyncio.run(main())