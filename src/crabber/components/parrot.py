import asyncio

from datetime import datetime
from typing import Callable, Awaitable

from apscheduler.triggers.interval import IntervalTrigger
from bilibili_api.dynamic import Dynamic
from bilibili_api.user import User
from bilibili_api.video import Video

from crabber.crabber import Crabber
from crabber.components import empty_handler
from crabber.misc import ensure_bili_url, jsonify, resize_bili_image
from crabber.qq_send import has_qq_service, send_qq_message
from crabber.rich_message import Block, Heading, Image, Inline, LinkButton, Paragraph, Quote, RichMessage, Text


default_events = []



def get_handler(
    ctx: Crabber,
    extra_uids: list[int] | None = None, favlists: list[int] | None = None,
    groups: list[int] | None = None, users: list[int] | None = None,
    interval: int = 600, cooldown: int = 5,
    *args, **kwargs,
) -> Callable[[dict], Awaitable[None]]:


    logger = ctx.logger
    dynamic_memory = {}

    extra_uids = extra_uids or []
    favlists = favlists or []
    groups = groups or []
    users = users or []

    async def parrot_forward_dynamic(dn: Dynamic, header: str="") -> None:

        if not has_qq_service(ctx):
            logger.warning("parrot requires qqbot or napcat service")
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

        message = build_dynamic_message(item, dn.get_dynamic_id(), header=header)

        if message.blocks:
            logger.debug(f"sending {message}")
            await send_qq_message(ctx, message, groups, users)
            logger.info(f"forwarded dynamic {dn.get_dynamic_id()} to group {groups} and user {users}")

        if dn.credential.has_sessdata():
            await parrot_post_process_noexcept(dn, item)


    async def parrot_fetch_dynamic() -> None:

        raw_uids = [ctx.uid, *extra_uids]
        uids = [uid for uid in raw_uids if uid > 0]

        if not uids:
            logger.warning(f"no valid uid found in {raw_uids}!")
            return

        if not ctx.room or not ctx.room.credential or not ctx.has_credential:
            logger.warning(f"get_dynamic requires credential to be configured")
            return

        for uid in uids:
            logger.debug(f"fetching dynamics for uid = {uid}")
            try:
                resp = await User(uid, ctx.room.credential).get_dynamics_new()
                dynamics = resp.get("items", [])

                for dynamic in dynamics:

                    dn = None
                    parrot_header = ""

                    if (id_str:=dynamic.get("id_str", "")):

                        # check if the dynamic has been handled before
                        if id_str in dynamic_memory: continue

                        # check dynamic publish date if pub_ts exists
                        if (pub_ts:=dynamic.get("modules", {}).get("module_author", {}).get("pub_ts", "")):
                            try:
                                pub_time = datetime.fromtimestamp(int(pub_ts))

                                if (ctx.init_time - pub_time).total_seconds() > interval:
                                    # ignore the dynamic which is published before the interval ahead of program start
                                    dynamic_memory[id_str] = True
                                    logger.debug(f"added dynamic {id_str} into memory, reason: {pub_time} is before {ctx.init_time}")
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
                                    parrot_header = f"{author_name}发布了视频"
                                    dn = Dynamic(dynamic_id, ctx.room.credential)
                                case "DYNAMIC_TYPE_DRAW":
                                    # some general types?
                                    parrot_header = f"{author_name}发布了动态"
                                    # dynamic["modules"]["module_dynamic"]["major"]["opus"]["summary"]["rich_text_nodes or text"]
                                    # dynamic["modules"]["module_dynamic"]["major"]["opus"]["pics"][?]["url"](http)
                                    dn = Dynamic(dynamic_id, ctx.room.credential)
                                case "DYNAMIC_TYPE_FORWARD":
                                    # dynamic["modules"]["module_dynamic"]["desc"]["rich_text_nodes or text"]
                                    # dynamic["orig"]["modules"]...
                                    parrot_header = f"{author_name}转发了内容"
                                    dn = Dynamic(dynamic_id, ctx.room.credential)
                                case _:
                                    logger.info(f"unknown dynamic type {dynamic_type}")
                                    logger.debug(jsonify(dynamic))

                    if dn:
                        await parrot_forward_dynamic(dn, parrot_header)
                        await asyncio.sleep(cooldown)
                        # Best-effort forwarding intentionally treats missed forwards as handled.
                        dynamic_memory[id_str] = True
                        logger.debug(f"added dynamic {id_str} into memory, reason: forward attempt complete")

            except Exception as e:
                logger.error(f"failed to fetch new dynamics: {e!r}")
            finally:
                await asyncio.sleep(cooldown)


    async def parrot_post_process_noexcept(dn: Dynamic, item: dict) -> None:

        # set like
        try:
            await dn.set_like(status=True) # why not
        except Exception as e:
            logger.info(f"failed to set like for dynamic {dn.get_dynamic_id()}: {e}")
        else:
            await asyncio.sleep(1)

        # try to pay coin(s) if it's a video
        try:
            if (bvid:=_get_bvid(item)):
                v = Video(bvid, credential=dn.credential)
                accept_coin_num = 1

                try:
                    v_info = await v.get_info()
                    copyright = int(v_info.get("copyright", 3))
                    if copyright == 1:
                        accept_coin_num = 2
                except Exception as e:
                    logger.warning(f"failed to get video info for {bvid}: {e}")

                _ = await asyncio.gather(
                    v.pay_coin(accept_coin_num),
                    v.set_favorite(add_media_ids=favlists),
                    return_exceptions=True,
                )
        except Exception as e:
            logger.info(f"failed to pay coin(s) and set favorite: {e}")


    ctx.scheduler.add_job( # type: ignore
        parrot_fetch_dynamic,
        IntervalTrigger(seconds=interval),
    )


    return empty_handler


# display width of dynamic pictures in markdown
SINGLE_PIC_WIDTH = 640
MULTI_PIC_WIDTH = 360
# 16:10, the usual ratio of video covers
VIDEO_COVER_WIDTH, VIDEO_COVER_HEIGHT = 640, 400


def build_dynamic_message(item: dict, dynamic_id: int | str, header: str="") -> RichMessage:

    modules = item.get("modules") or {}
    orig = item.get("orig") or {}
    orig_modules = orig.get("modules") or {}

    main_blocks, main_buttons = build_blocks_from_module(modules.get("module_dynamic") or {})
    orig_blocks, orig_buttons = build_blocks_from_module(orig_modules.get("module_dynamic") or {})

    message = RichMessage()

    if not main_blocks and not orig_blocks:
        return message

    if header:
        message.blocks.append(Heading(header))

    message.blocks += main_blocks

    if orig_blocks:
        orig_author = (orig_modules.get("module_author") or {}).get("name", "")
        title = f"原动态 @{orig_author}" if orig_author else "原动态"
        message.blocks.append(Quote([Paragraph([Text(title, bold=True)]), *orig_blocks]))

    message.buttons += main_buttons + orig_buttons

    # a video already comes with its own link
    if not _get_bvid(item):
        message.buttons.append(LinkButton("打开动态", f"https://t.bilibili.com/{dynamic_id}"))

    return message


def build_blocks_from_module(module_dynamic: dict) -> tuple[list[Block], list[LinkButton]]:

    major = module_dynamic.get("major") or {}

    blocks: list[Block] = []
    blocks += desc_to_blocks(module_dynamic.get("desc") or {})
    blocks += opus_to_blocks(major.get("opus") or {})

    archive_blocks, buttons = archive_to_blocks(major.get("archive") or {})
    blocks += archive_blocks

    return blocks, buttons


def desc_to_blocks(desc: dict) -> list[Block]:

    inlines: list[Inline] = []

    if (rich_text_nodes := desc.get("rich_text_nodes")):
        inlines = rich_text_to_inlines(rich_text_nodes)
    elif (text := desc.get("text")):
        inlines = [Text(text)]

    if not inlines:
        return []

    return [Paragraph(inlines)]


def opus_to_blocks(opus: dict) -> list[Block]:

    blocks: list[Block] = []

    if (title := (opus.get("title") or "").strip()):
        blocks.append(Paragraph([Text(title, bold=True)]))

    summary = opus.get("summary") or {}

    if (rich_text_nodes := summary.get("rich_text_nodes")):
        blocks.append(Paragraph(rich_text_to_inlines(rich_text_nodes)))
    elif (text := summary.get("text")):
        blocks.append(Paragraph([Text(text)]))

    pics = [pic for pic in (opus.get("pics") or []) if isinstance(pic, dict) and isinstance(pic.get("url"), str) and pic["url"]]
    max_width = SINGLE_PIC_WIDTH if len(pics) == 1 else MULTI_PIC_WIDTH

    if pics:
        blocks.append(Paragraph([
            Image(ensure_bili_url(pic["url"]), *_fit_size(pic.get("width"), pic.get("height"), max_width), alt="图片")
            for pic in pics
        ]))

    return blocks


def archive_to_blocks(archive: dict) -> tuple[list[Block], list[LinkButton]]:

    blocks: list[Block] = []
    buttons: list[LinkButton] = []

    title: str = (archive.get("title") or "").strip()
    cover: str = archive.get("cover") or ""
    bvid: str = archive.get("bvid") or ""
    jump_url: str = ensure_bili_url((archive.get("jump_url") or "").strip())

    if cover:
        if (resized := resize_bili_image(cover, VIDEO_COVER_WIDTH, VIDEO_COVER_HEIGHT)):
            blocks.append(Paragraph([Image(resized, VIDEO_COVER_WIDTH, VIDEO_COVER_HEIGHT, alt="视频封面")]))
        else:
            blocks.append(Paragraph([Image(ensure_bili_url(cover), alt="视频封面")]))

    if title:
        blocks.append(Paragraph([Text(title, bold=True)]))

    if not jump_url and bvid:
        jump_url = f"https://www.bilibili.com/video/{bvid}"

    if jump_url:
        buttons.append(LinkButton("打开视频", jump_url))

    return blocks, buttons


def rich_text_to_inlines(nodes: list) -> list[Inline]:

    inlines: list[Inline] = []

    for node in nodes:
        if not isinstance(node, dict): continue

        text = node.get("text") or ""

        match node.get("type", ""):
            case "RICH_TEXT_NODE_TYPE_EMOJI":
                icon = ensure_bili_url((node.get("emoji") or {}).get("icon_url") or "")
                if icon:
                    inlines.append(Image(icon, alt=text, emoji=True))
                elif text:
                    inlines.append(Text(text))
            case _:
                # text, @, topic, link and unknown node types: keep the text
                if text:
                    inlines.append(Text(text))

    return inlines


def _fit_size(width: object, height: object, max_width: int) -> tuple[int, int]:
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return 0, 0
    if width <= max_width:
        return width, height
    return max_width, max(1, round(height * max_width / width))


def _get_bvid(dynamic_info_item: dict) -> str | None:
    modules = dynamic_info_item.get("modules") or {}
    module_dynamic = modules.get("module_dynamic") or {}
    major = module_dynamic.get("major") or {}
    archive = major.get("archive") or {}
    bvid = archive.get("bvid") or None
    return bvid
