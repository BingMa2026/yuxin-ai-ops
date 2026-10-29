import asyncio
import base64
import io
import json
import wave
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from app.core.exceptions import CustomException

from .capabilities import speech_adapter, speech_endpoint

MAX_AUDIO_BYTES = 60 * 16000 * 2 + 4096


def inspect_audio(audio: bytes, limit_seconds: int) -> tuple[bytes, int]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            if reader.getnchannels() != 1 or reader.getsampwidth() != 2 or reader.getframerate() != 16000 or reader.getcomptype() != "NONE":
                raise ValueError("format")
            frames = reader.getnframes()
            if frames < 1600 or frames > limit_seconds * 16000:
                raise ValueError("duration")
            pcm = reader.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError("truncated")
        return pcm, (frames * 1000 + 15999) // 16000
    except (wave.Error, EOFError, ValueError) as exc:
        raise CustomException(msg=f"录音格式无效，请重新录制（最长 {limit_seconds} 秒）", status_code=400) from exc


async def transcribe(endpoint: str, model_id: str, api_key: str, audio: bytes, pcm: bytes, protocol: str | None = None) -> str:
    if not api_key:
        raise CustomException(msg="语音服务尚未配置密钥", status_code=503)
    headers = {"Authorization": f"Bearer {api_key}"}
    protocol = speech_adapter(model_id, protocol)
    url = speech_endpoint(endpoint, protocol)
    async with asyncio.timeout(65):
        if protocol == "qwen_realtime":
            return await _realtime(url, model_id, headers, pcm)
        if protocol == "dashscope_realtime":
            return await _dashscope_realtime(url, model_id, headers, pcm)
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            messages = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(audio).decode()}}]}]
            if protocol == "openai_transcriptions":
                response = await client.post(url, headers=headers, files={"file": ("voice.wav", audio, "audio/wav")}, data={"model": model_id, "response_format": "json"})
            elif protocol == "dashscope_asr":
                response = await client.post(
                    url, headers={**headers, "X-DashScope-SSE": "disable"}, json={"model": model_id, "input": {"messages": messages}, "parameters": {"format": "wav", "sample_rate": "16000"}}
                )
            else:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model_id,
                        "messages": messages,
                        "stream": False,
                        "asr_options": {"enable_itn": True},
                    },
                )
        if response.status_code != 200:
            raise CustomException(msg="语音识别服务暂时不可用，请稍后重试", status_code=502)
        result = response.json()
        value = (
            result.get("text")
            if protocol == "openai_transcriptions"
            else result.get("output", {}).get("text")
            if protocol == "dashscope_asr"
            else result.get("choices", [{}])[0].get("message", {}).get("content")
        )
        if not isinstance(value, str):
            raise ValueError("invalid transcription response")
        return value.strip()


async def _realtime(url: str, model_id: str, headers: dict, pcm: bytes) -> str:
    async with connect(f"{url}?model={model_id}", additional_headers=headers, open_timeout=10, close_timeout=2, max_size=1024 * 1024, proxy=None) as websocket:

        async def send(kind, **payload):
            await websocket.send(json.dumps({"event_id": uuid4().hex, "type": kind, **payload}))

        await send("session.update", session={"input_audio_format": "pcm", "sample_rate": 16000, "turn_detection": None})
        async for raw in websocket:
            event = json.loads(raw)
            if event.get("type") == "error":
                raise ValueError("speech upstream error")
            if event.get("type") == "session.updated":
                break
        for offset in range(0, len(pcm), 32000):
            await send("input_audio_buffer.append", audio=base64.b64encode(pcm[offset : offset + 32000]).decode())
        await send("input_audio_buffer.commit")
        await send("session.finish")
        transcripts: dict[str, str] = {}
        async for raw in websocket:
            event = json.loads(raw)
            kind = event.get("type")
            if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
                raise ValueError("speech upstream error")
            if kind == "conversation.item.input_audio_transcription.completed":
                value = event.get("transcript")
                if not isinstance(value, str):
                    raise ValueError("invalid transcription")
                transcripts[str(event.get("item_id", "utterance"))] = value
            if kind == "session.finished":
                return "".join(transcripts.values()).strip()
        raise ValueError("speech session ended before completion")


async def _dashscope_realtime(url: str, model_id: str, headers: dict, pcm: bytes) -> str:
    # 8 kHz telephone models use the same protocol, with downsampled PCM.
    sample_rate = 8000 if "8k" in model_id else 16000
    if sample_rate == 8000:
        import struct

        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        pcm = b"".join(struct.pack("<h", (a + b) // 2) for a, b in zip(samples[::2], samples[1::2], strict=False))
    async with connect(url, additional_headers=headers, open_timeout=10, close_timeout=2, max_size=1024 * 1024, proxy=None) as websocket:
        task_id = uuid4().hex
        await websocket.send(
            json.dumps(
                {
                    "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
                    "payload": {"task_group": "audio", "task": "asr", "function": "recognition", "model": model_id, "parameters": {"format": "pcm", "sample_rate": sample_rate}, "input": {}},
                }
            )
        )
        async for raw in websocket:
            kind = json.loads(raw).get("header", {}).get("event")
            if kind == "task-failed":
                raise ValueError("speech upstream error")
            if kind == "task-started":
                break
        else:
            raise ValueError("speech task did not start")
        for offset in range(0, len(pcm), 3200):
            await websocket.send(pcm[offset : offset + 3200])
        await websocket.send(json.dumps({"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}))
        sentences = {}
        async for raw in websocket:
            event = json.loads(raw)
            kind = event.get("header", {}).get("event")
            if kind == "task-failed":
                raise ValueError("speech upstream error")
            if kind == "result-generated":
                sentence = event.get("payload", {}).get("output", {}).get("sentence", {})
                if sentence.get("sentence_end") and not sentence.get("heartbeat"):
                    value = sentence.get("text")
                    if not isinstance(value, str):
                        raise ValueError("invalid transcription")
                    sentences[str(sentence.get("begin_time"))] = value
            if kind == "task-finished":
                return "".join(sentences.values()).strip()
        raise ValueError("speech task ended before completion")
