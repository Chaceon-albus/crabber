import asyncio
import logging

from typing import ClassVar

from dashscope.audio import asr
# import dashscope.audio.asr.recognition as recognition

from .interface import BaseService


# Monkeypatch dashscope's RecognitionResult to fix a bug in the SDK
# where RecognitionResult.__init__ fails to copy/initialize the `headers` field,
# leading to a KeyError: 'headers' when serializing/printing the result.
# _original_recognition_result_init = recognition.RecognitionResult.__init__

# def _patched_recognition_result_init(self, response, sentences=None, usages=None):
#     _original_recognition_result_init(self, response, sentences, usages) # type: ignore
#     self.headers = getattr(response, "headers", None)

# recognition.RecognitionResult.__init__ = _patched_recognition_result_init


class AsrService(BaseService):

    service_name: ClassVar[str] = "asr"

    def __init__(self, config: dict, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.provider = self.config.get("provider")

    def new_session(
        self,
        fun_asr_callback: asr.RecognitionCallback | None = None,
    ) -> FunAsrSession | DoubaoAsrSession:
        match self.provider:
            case "fun-asr":
                if not fun_asr_callback:
                    raise ValueError(f"wanted RecognitionCallback for fun_asr_callback but got {type(fun_asr_callback)}")
                asr_params = self.config.get("fun_asr_params", {})
                if "api_key" not in asr_params:
                    raise ValueError("api_key not configured in asr_params")
                return FunAsrSession(fun_asr_callback, asr_params)
            case "doubao-asr":
                return DoubaoAsrSession()
            case _:
                raise ValueError(f"unknown asr provider: {self.provider}")



# https://help.aliyun.com/zh/model-studio/fun-asr-realtime-python-sdk
class FunAsrSession:

    def __init__(self, callback: asr.RecognitionCallback, asr_params: dict) -> None:

        params = {
            "model": "fun-asr-realtime",
            "format": "wav", # use PCM encoding
            "sample_rate": 16000, # 16 kHz only
            "semantic_punctuation_enabled": True,
            "heartbeat": True,
            **asr_params,
        }

        self.recognition = asr.Recognition(
            # api_key=self.__api_key, # let it overwrite by **params
            **params,
            callback=callback,
        )

        self.is_running = False


    async def stop(self) -> None:
        try:
            await asyncio.to_thread(self.recognition.stop)
        except Exception:
            pass

        self.is_running = False


    async def send_audio_frame(self, buffer: bytes) -> None:
        if not self.is_running:
            self.recognition.start()
            self.is_running = True

        # non-blocking, just put into a queue underlying
        self.recognition.send_audio_frame(buffer)


    def __del__(self):
        if self.is_running:
            try:
                self.recognition.stop()
            except Exception:
                pass
            finally:
                self.is_running = False


class DoubaoAsrSession:

    def __init__(self) -> None:
        raise RuntimeError("not implemented")

    async def stop(self) -> None:
        pass

    async def send_audio_frame(self, buffer: bytes) -> None:
        pass
