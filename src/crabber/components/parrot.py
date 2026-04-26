import asyncio

from datetime import datetime
from typing import Callable, Awaitable

from apscheduler.triggers.interval import IntervalTrigger
from bilibili_api.dynamic import Dynamic
from bilibili_api.user import User

from crabber.crabber import Crabber
from crabber.services import NapCatService
from crabber.components import empty_handler
from crabber.misc import jsonify


default_events = []



def get_handler(ctx: Crabber, groups: list = [], users: list = [], interval: int = 600, cooldown: int = 5, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:


    logger = ctx.logger
    dynamic_memory = {}


    async def parrot_forward_dynamic(dn: Dynamic, prefix: str="") -> None:
        try:
            if dn.credential.has_sessdata():
                await dn.set_like(status=True) # why not
        except Exception as e:
            logger.info(f"failed to set like for dynamic {dn.get_dynamic_id()}: {e}")

        s = ctx.services.get("napcat")
        napcat = s if isinstance(s, NapCatService) else None

        if not napcat:
            logger.warning("napcat not found, skip")
            return

        try:
            info = await dn.get_info()
            item = info.get("item", {})
        except Exception as e:
            logger.error(f"failed to get dynamic details: {e}")
            return

        # DYNAMIC_TYPE_AV
        # info["modules"]["module_dynamic"]["desc"]["rich_text_nodes or text"]
        # info["modules"]["module_dynamic"]["major"]["archive"] -> bvid, cover(http), title
        # DYNAMIC_TYPE_DRAW or DYNAMIC_TYPE_FORWARD
        # info["modules"]["module_dynamic"]["major"]["opus"]["summary"]["rich_text_nodes or text"]
        # info["modules"]["module_dynamic"]["major"]["opus"]["pics"][?]["url"](http)
        # info["orig"]["modules"]...

        # module_dynamic parse logic:
        # 1. desc -> rich_text_nodes or text
        # 2. major -> opus -> summary + pics
        # 3. orig -> modules -> module_dynamic -> (1) + (2)

        content = []
        content += build_message_from_module(item.get("modules", {}).get("module_dynamic", {}), prefix=prefix)
        content += build_message_from_module(item.get("orig", {}).get("modules", {}).get("module_dynamic", {}), prefix="\n原动态：\n")

        if content:
            logger.debug(f"sending {content}")
            await napcat.send_msg_concurrently(content, groups, users)


    async def parrot_fetch_dynamic() -> None:

        if ctx.uid < 0:
            logger.warning(f"invalid uid {ctx.uid}")
            return

        if not ctx.room or not ctx.room.credential or not ctx.has_credential:
            logger.warning(f"get_dynamic requires credential to be configured")
            return

        try:
            resp = await User(ctx.uid, ctx.room.credential).get_dynamics_new()
            dynamics = resp.get("items", [])

            for dynamic in dynamics:

                dn = None
                parrot_prefix = ""

                if (id_str:=dynamic.get("id_str", "")):

                    # check if the dynamic has been handled before
                    if id_str in dynamic_memory: continue

                    # check dynamic publish date if pub_ts exists
                    if (pub_ts:=dynamic.get("modules", {}).get("module_author", {}).get("pub_ts", "")):
                        try:
                            pub_time = datetime.fromtimestamp(int(pub_ts))
                            if (datetime.now() - pub_time).total_seconds() > 2 * interval:
                                # likely to be published before the program start
                                # since it's too long time ago, simple ignore it
                                dynamic_memory[id_str] = True
                                logger.debug(f"added dynamic {id_str} into memory")
                                continue
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
                                dn = Dynamic(dynamic_id, ctx.room.credential)
                            case "DYNAMIC_TYPE_DRAW":
                                # some general types?
                                parrot_prefix = f"{author_name}发布了动态：\n"
                                # dynamic["modules"]["module_dynamic"]["major"]["opus"]["summary"]["rich_text_nodes or text"]
                                # dynamic["modules"]["module_dynamic"]["major"]["opus"]["pics"][?]["url"](http)
                                dn = Dynamic(dynamic_id, ctx.room.credential)
                            case "DYNAMIC_TYPE_FORWARD":
                                # dynamic["modules"]["module_dynamic"]["desc"]["rich_text_nodes or text"]
                                # dynamic["orig"]["modules"]...
                                parrot_prefix = f"{author_name}转发了内容：\n"
                                dn = Dynamic(dynamic_id, ctx.room.credential)
                            case _:
                                logger.info(f"unknown dynamic type {dynamic_type}")
                                logger.debug(jsonify(dynamic))

                if dn:
                    await parrot_forward_dynamic(dn, parrot_prefix)
                    await asyncio.sleep(cooldown)
                    # marked the id_str on success
                    dynamic_memory[id_str] = True
                    logger.debug(f"added dynamic {id_str} into memory")

        except Exception as e:
            logger.error(f"failed to fetch new dynamics: {e}")



    ctx.scheduler.add_job( # type: ignore
        parrot_fetch_dynamic,
        IntervalTrigger(seconds=interval),
    )


    return empty_handler


def build_message_from_module(module_dynamic: dict, prefix: str="") -> list[dict]:

    content = []

    desc = module_dynamic.get("desc", {})
    major = module_dynamic.get("major", {})

    # make sure all dict
    desc = desc if desc else {}
    major = major if major else {}

    opus = major.get("opus", {})
    archive = major.get("archive", {})

    # make sure all dict
    opus = opus if opus else {}
    archive = archive if archive else {}

    if desc or opus or archive:

        if prefix:
            content += [{
                "type": "text",
                "data": { "text": prefix }
            }]

        content += desc_to_message(desc)
        content += opus_to_message(opus)
        content += archive_to_message(archive)


    return content


def ensure_bili_url(url: str) -> str:
    url = f"https:{url}" if url.startswith("//") else url
    url.replace("http://", "https://")
    return url


def desc_to_message(desc: dict) -> list[dict]:

    rich_text_nodes = desc.get("rich_text_nodes", [])
    text = desc.get("text", "")

    if rich_text_nodes:
        content = rich_text_to_message(rich_text_nodes)
    else:
        content = [{
            "type": "text",
            "data": { "text": text }
        }]

    return content


def opus_to_message(opus: dict) -> list[dict]:

    content = []

    if (title:=opus.get("title", "")):
        content += [{
            "type": "text",
            "data": { "text": f"{title}\n" }
        }]

    summary = opus.get("summary", {})
    archive = opus.get("archive", {})

    summary = summary if summary else {}
    archive = archive if archive else {}

    if summary:
        # normal dynamic
        rich_text_nodes = summary.get("rich_text_nodes", [])
        text = summary.get("text", "")

        if rich_text_nodes:
            content += rich_text_to_message(rich_text_nodes)
            content += [{
                "type": "text",
                "data": { "text": "\n" }
            }]
        elif text:
            # fallback to text
            content += [{
                "type": "text",
                "data": { "text": text }
            }, {
                "type": "text",
                "data": { "text": "\n" }
            }]
        else:
            # should not happen?
            pass

    if archive:
        # publish video dynamic
        pass

    for pic in opus.get("pics", []):
        if not isinstance(pic, dict): continue
        url: str = pic.get("url", "")
        if isinstance(url, str):
            content += [{
                "type": "image",
                "data": { "file": ensure_bili_url(url) }
            }]

    if content:
        last_chunk = content[-1]
        if last_chunk["type"]=="text" and last_chunk["data"]["text"]=="\n":
            # trim the tailing newline
            content.pop(-1)

    return content


def archive_to_message(archive: dict) -> list[dict]:

    content = []

    title: str = archive.get("title", "")
    cover: str = ensure_bili_url(archive.get("cover", ""))
    jump_url: str = ensure_bili_url(archive.get("jump_url", ""))

    if cover:
        # no need to add additional line after an image
        content += [{
            "type": "image",
            "data": { "file": cover }
        }]

    if title:
        content += [{
            "type": "text",
            "data": { "text": title.strip() }
        }, {
            "type": "text",
            "data": { "text": "\n" }
        }]

    if jump_url:
        content += [{
            "type": "text",
            "data": { "text": jump_url.strip() }
        }, {
            "type": "text",
            "data": { "text": "\n" }
        }]

    return content


def rich_text_to_message(nodes: list) -> list[dict]:

    content = []

    for node in nodes:
        match node.get("type", ""):
            case "RICH_TEXT_NODE_TYPE_TEXT":
                if text:=node.get("text"):
                    content += [{
                        "type": "text",
                        "data": { "text": text }
                    }]
            case "RICH_TEXT_NODE_TYPE_AT":
                if text:=node.get("text"):
                    content += [{
                        "type": "text",
                        "data": { "text": text }
                    }]
            case "RICH_TEXT_NODE_TYPE_EMOJI":
                icon = ensure_bili_url(node.get("emoji", {}).get("icon_url", ""))
                text = node.get("text", "")
                if icon:
                    content += [{
                        "type": "image",
                        "data": { "file": icon }
                    }]
                else:
                    content += [{
                        "type": "text",
                        "data": { "text": text }
                    }]
            case _:
                # unknown node type, try to extract text
                if text:=node.get("text"):
                    content += [{
                        "type": "text",
                        "data": { "text": text }
                    }]

    return content
