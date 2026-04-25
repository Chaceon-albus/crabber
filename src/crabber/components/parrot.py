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



def get_handler(ctx: Crabber, interval: int = 600, cooldown: int = 5, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:


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

        # DYNAMIC_TYPE_AV
        # info["modules"]["module_dynamic"]["desc"]["rich_text_nodes or text"]
        # info["modules"]["module_dynamic"]["major"]["archive"] -> bvid, cover(http), title
        # DYNAMIC_TYPE_DRAW or DYNAMIC_TYPE_FORWARD
        # info["modules"]["module_dynamic"]["major"]["opus"]["summary"]["rich_text_nodes or text"]
        # info["modules"]["module_dynamic"]["major"]["opus"]["pics"][?]["url"](http)
        # dynamic["orig"]["modules"]...

        # module_dynamic parse logic:
        # 1. desc -> rich_text_nodes or text
        # 2. major -> opus -> summary + pics
        # 3. orig -> modules -> module_dynamic -> (1) + (2)


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

        except Exception as e:
            logger.error(f"failed to fetch new dynamics: {e}")



    ctx.scheduler.add_job( # type: ignore
        parrot_fetch_dynamic,
        IntervalTrigger(seconds=interval),
    )


    return empty_handler