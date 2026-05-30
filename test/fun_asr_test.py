import argparse
import asyncio
import json

from datetime import timedelta

import aiofiles

from dashscope.audio import asr

from crabber.services.asr import AsrService, FunAsrSession
from crabber.logging import logger as default_logger


class TestRecognitionCallback(asr.RecognitionCallback):

    def __init__(self) -> None:
        pass

    def on_complete(self) -> None:
        print("recognition complete!")

    def on_error(self, result: asr.RecognitionResult) -> None:
        raise RuntimeError(result.request_id, result.message)

    def on_event(self, result: asr.RecognitionResult) -> None:
        sentence = result.get_sentence()
        sentence = sentence if not isinstance(sentence, list) else sentence[0]

        if "text" in sentence:
            content = sentence.get("text", "").strip()
            if not content: return

            if asr.RecognitionResult.is_sentence_end(sentence):
                srt_begin = timedelta(milliseconds=sentence.get("begin_time", 0))
                srt_end = timedelta(milliseconds=sentence.get("end_time", 1000))
                print(f"{srt_begin} -> {srt_end}: {content}")
            else:
                pass


async def main(args: argparse.Namespace) -> None:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    asr_service_conf = {}

    for service in config.get("crabbers", [])[0].get("services", []):
        if service["type"] == "asr":
            asr_service_conf = service["config"]
            break

    if not asr_service_conf:
        print("asr config not found")
        return

    asr_service = AsrService(asr_service_conf, default_logger)

    session = asr_service.new_session(
        fun_asr_callback=TestRecognitionCallback(),
    )

    if not isinstance(session, FunAsrSession):
        print(f"got {type(session)} instead of FunAsrSession")
        return

    async with aiofiles.open(args.fn, mode="rb") as f:
        while True:
            chunk = await f.read(3200)
            if not chunk: break
            await session.send_audio_frame(chunk)
            # 3200 bytes is 0.1 seconds of 16kHz 16-bit mono audio.
            # Sleep 0.1 seconds to simulate real-time streaming.
            await asyncio.sleep(0.1)

    print("Finished sending all audio chunks. Waiting for final results...")
    await session.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fn", type=str)

    args = parser.parse_args()

    asyncio.run(main(args))
