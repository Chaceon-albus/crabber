import asyncio
import shutil

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Awaitable

from dashscope.audio.asr import RecognitionCallback as FunAsrCallback
from dashscope.audio.asr import RecognitionResult as FunAsrResult

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.ffmpeg import FFmpegProcess
from crabber.services import AsrService, LlmService
from crabber.services.asr import FunAsrSession, DoubaoAsrSession
from crabber.components import empty_handler
from crabber.misc import coin_to_cny


default_events = []


class SpeechType(Enum):
    TEXT = 0
    VOCAL = 1
    UNKNOWN = -1


@dataclass
class Speech:
    content: str
    begin: timedelta
    end: timedelta
    speech_type: SpeechType = SpeechType.TEXT


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    speech_list: list[Speech] = []
    user_events: list[str] = []

    speech_pos = 0
    event_pos = 0

    iris_transcribe_event = asyncio.Event()


    class IrisFunAsrCallback(FunAsrCallback):

        def __init__(self) -> None:
            super().__init__()

        def on_complete(self) -> None:
            logger.info("fun-asr recognition complete")
            return super().on_complete()

        def on_error(self, result: FunAsrResult) -> None:
            logger.error(f"fun-asr error: {result.message} (req_id: {result.request_id})")

            # TODO: robust error handling
            async def _handle_error():
                nonlocal asr_session
                if asr_session:
                    logger.warning("stop asr session due to callback error...")
                    await asr_session.stop()
                    asr_session = None

            if ctx.loop and ctx.loop.is_running():
                ctx.loop.call_soon_threadsafe(
                    lambda: ctx.add_task(_handle_error())
                )

        def on_event(self, result: FunAsrResult) -> None:
            sentence = result.get_sentence()
            sentence = sentence if not isinstance(sentence, list) else sentence[0]

            if "text" in sentence:
                content = sentence.get("text", "").strip()
                if not content: return

                if FunAsrResult.is_sentence_end(sentence):
                    speech_begin = timedelta(milliseconds=sentence.get("begin_time", 0))
                    speech_end = timedelta(milliseconds=sentence.get("end_time", 1000))

                    # TODO: use debug level
                    logger.info(f"{speech_begin} -> {speech_end}: {content}")

                    speech = Speech(
                        content=content,
                        begin=speech_begin,
                        end=speech_end,
                    )

                    if ctx.loop and ctx.loop.is_running():
                        ctx.loop.call_soon_threadsafe(speech_list.append, speech)
                        ctx.loop.call_soon_threadsafe(iris_transcribe_event.set)
                else:
                    # sentence not complete
                    pass

            return super().on_event(result)


    asr = ctx.get_service(AsrService)
    llm = ctx.get_service(LlmService)

    asr_session: FunAsrSession | DoubaoAsrSession | None = None
    llm_chat = None

    if not (isinstance(asr, AsrService) and isinstance(llm, LlmService)):
        logger.warning("asr or llm service not configured, skip iris")
        return empty_handler

    if not (ffmpeg_path:=shutil.which("ffmpeg")):
        logger.warning("ffmpeg not found, skip iris")
        return empty_handler

    ffmpeg_process: FFmpegProcess | None = None
    ffmpeg_event = asyncio.Event()


    async def _iris_danmaku_handler(event: dict) -> None:
        info = event.get("data", {}).get("info", {})
        if len(info) > 2 and len(info[2]) > 1:
            msg = info[1]
            uid = info[2][0]
            usr = info[2][1]
            # skip self danmaku
            if uid == ctx.cred_manager.uid: return
            user_events.append(f"{usr}：{msg}")


    async def _iris_gift_handler(event: dict) -> None:
        cmd = event.get("data", {}).get("cmd", "unknown")
        data = event.get("data", {}).get("data", {})

        match cmd:
            case "SEND_GIFT":
                uname = data.get("uname", "[unknown]")
                user = data.get("sender_uinfo", {}).get("base", {}).get("name", uname)

                action = data.get("action", "投喂")
                gift_name = data.get("giftName", "[unknown]")
                num = data.get("num", 1)
                price = data.get("price", 0)
                value_in_cny = coin_to_cny(price * num)

                user_events.append(f"{user} {action}了 {gift_name}×{num}，价值￥{value_in_cny:.2f}")

            case "USER_TOAST_MSG":
                num  = data.get("num", 1)
                unit = data.get("unit", "月")
                role = data.get("role_name", "舰长")
                user = data.get("username", "[unknown]")
                price = data.get("price", 0) # this is total price, not unit price
                value_in_cny = coin_to_cny(price)

                user_events.append(f"{user} 开通了{num}个{unit}的{role}，价值￥{value_in_cny:.2f}")

            case "SUPER_CHAT_MESSAGE":
                user = data.get("user_info", {}).get("uname", "[unknown]")
                message = data.get("message", "")
                value_in_cny = data.get("price", 0) # CNY price

                user_events.append(f"{user} 发送了￥{value_in_cny:.2f}的醒目留言: {message}")

            case _:
                pass


    async def _iris_online(_: RoomInfo) -> None:
        nonlocal asr_session
        match asr.provider:
            case "fun-asr":
                asr_session = asr.new_session(
                    fun_asr_callback=IrisFunAsrCallback(),
                )

            case "doubao-asr":
                logger.warning(f"{asr.provider} not implemented")

            case _:
                logger.warning(f"unknown asr provider {asr.provider}")

        nonlocal speech_list, speech_pos, user_events, event_pos, llm_chat
        speech_list.clear()
        user_events.clear()
        speech_pos = 0
        event_pos = 0

        old_chat = llm_chat
        llm_chat = 0 # TODO: fix


    async def _iris_offline(_: RoomInfo) -> None:
        nonlocal asr_session
        if asr_session:
            await asr_session.stop()
            asr_session = None

        await asyncio.sleep(30) # let llm or something else to cooldown
        # TODO: cleanup


    async def _iris_encoder(sample_rate: int = 16000) -> None:

        queue = asyncio.Queue(maxsize=128)

        while ctx.room_info.stream is None:
            logger.warning(f"stream is None, skip encoding")
            await asyncio.sleep(1)

        ctx.room_info.stream.subscribe(queue)

        nonlocal ffmpeg_process
        while True:
            try:
                data: bytes | None = await queue.get()
                if data is None:
                    if ffmpeg_process is not None:
                        logger.info(f"stop encoding wav")
                        await ffmpeg_process.close()
                        ffmpeg_process = None
                else:
                    if ffmpeg_process is None or not ffmpeg_process.is_running:
                        ffmpeg_process = FFmpegProcess(
                            args=[
                                "-hide_banner",
                                "-nostdin", "-y",
                                "-i", "pipe:0"
                                "-vn",
                                "-ac", "1", # mono
                                "-ar", f"{sample_rate}",
                                "-acodec", "pcm_s16le",
                                "-f", "wav", "pipe:1",
                            ],
                            ffmpeg_path=ffmpeg_path,
                            logger=logger,
                        )
                        await ffmpeg_process.start()
                        ffmpeg_event.set()
                        logger.info("start to encode wav")

                    await ffmpeg_process.write(data)
            except asyncio.CancelledError:
                logger.info("iris encoder task cancelled")
                if ffmpeg_process is not None:
                    await ffmpeg_process.close()
                    ffmpeg_process = None
            except Exception as e:
                logger.error(f"iris error during encoding: {e}")
                if ffmpeg_process is not None:
                    await ffmpeg_process.close()
                    ffmpeg_process = None


    async def _iris_transcriber() -> None:
        while True:
            try:
                if ffmpeg_process is None:
                    await ffmpeg_event.wait()
                    ffmpeg_event.clear()

                if ffmpeg_process is None:
                    logger.error("ffmpeg event triggered but ffmpeg_process is still None")
                    continue

                data = await ffmpeg_process.read_stdout()

                if asr_session:
                    await asr_session.send_audio_frame(data)

            except asyncio.CancelledError:
                logger.info("iris transcriber task cancelled")
            except Exception as e:
                logger.error(f"iris error during transcription: {e}")


    async def _iris_llm() -> None:
        while True:
            await iris_transcribe_event.wait()
            iris_transcribe_event.clear()

            speech = speech_list.copy()
            uevent = user_events.copy()

            nonlocal speech_pos, event_pos

            # at least 1 speech
            if speech_pos < len(speech) and event_pos <= len(uevent):
                spos = speech_pos
                epos = event_pos

                # move to the end
                speech_pos = len(speech)
                event_pos = len(uevent)

                speech = speech[spos:]
                uevent = uevent[epos:]
            else:
                continue

            prompt = "主播说：\n"

            for s in speech:
                prompt += f"{s.content.strip()}\n"

            prompt += "\n\n用户消息：\n"
            prompt += "\n".join([ue.strip() for ue in uevent])

            # TODO: use debug level
            logger.info(f"send llm prompt:\n{prompt}")



    ctx.add_handler("DANMU_MSG", _iris_danmaku_handler)
    for en in ["SEND_GIFT", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE"]:
        ctx.add_handler(en, _iris_gift_handler)

    ctx.add_online_callback(_iris_online)
    ctx.add_offline_callback(_iris_offline)

    ctx.add_task(_iris_encoder())
    ctx.add_task(_iris_transcriber())
    ctx.add_task(_iris_llm())


    return empty_handler
