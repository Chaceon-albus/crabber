import asyncio
import json

from crabber.services import init_services, NapCatService


async def main():
    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)

    services = await init_services(config["crabbers"][0]["services"])

    napcat: NapCatService = services["napcat"] # type: ignore

    # await napcat.send_msg(
    #     message_type="private",
    #     user_id="1145141919810",
    #     message="[CQ:image,file=https://example.com/image.jpg]测试一下图片"
    # )

    # await napcat.send_msg(
    #     message_type="group",
    #     group_id="114514",
    #     message="[CQ:image,file=https://example.com/image.jpg]测试一下带图片消息"
    # )

    while action := input("action: ").strip():
        params = {}
        while key := input("  key: ").strip():
            value = input("  value: ").strip()
            # try to parse value as JSON (for numbers, lists, bools, etc.)
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
            params[key] = value
        resp = await getattr(napcat, action)(json=params)
        print(json.dumps(resp, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
