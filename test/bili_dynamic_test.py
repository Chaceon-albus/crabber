import asyncio
import json

import bilibili_api as biliapi

from crabber.misc import jsonify


async def main():
    print(jsonify(await biliapi.dynamic.Dynamic(1194816136075542545).get_info()))

    # with open("credential.json") as f:
    #     cred = json.load(f)

    # credential = biliapi.Credential(**cred)

    # dynamics = await biliapi.user.User(9617619, credential).get_dynamics_new()
    # print(jsonify(dynamics))


if __name__ == "__main__":
    asyncio.run(main())