import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.v1.module_speech import provider


@pytest.mark.parametrize("protocol,expected", [("qwen_asr", "choices"), ("dashscope_asr", "output"), ("openai_transcriptions", "text")])
async def test_http_protocol_payload_and_extraction(monkeypatch, protocol, expected):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = httpx.Response(200, json={"choices": [{"message": {"content": "识别完成"}}], "output": {"text": "识别完成"}, "text": "识别完成"})
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **kwargs: client)
    assert await provider.transcribe("https://dashscope.aliyuncs.com/compatible-mode/v1", "new-model-2030", "test-key", b"wav", b"pcm", protocol) == "识别完成"
    args, kwargs = client.post.call_args
    if protocol == "openai_transcriptions":
        assert args[0].endswith("/audio/transcriptions")
        assert kwargs["files"]["file"][1] == b"wav"
        assert kwargs["data"]["model"] == "new-model-2030"
    elif protocol == "dashscope_asr":
        assert kwargs["json"]["input"]["messages"][0]["content"][0]["input_audio"]["data"].startswith("data:audio/wav;base64,")
    else:
        assert kwargs["json"]["asr_options"]["enable_itn"]


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = next(self.events, None)
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)

    async def send(self, payload):
        self.sent.append(payload)


async def test_realtime_commits_recording_deduplicates_and_requires_completion(monkeypatch):
    events = [
        {"type": "session.updated"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "one", "transcript": "你好"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "one", "transcript": "你好"},
        {"type": "session.finished"},
    ]
    socket = Socket(events)
    monkeypatch.setattr(provider, "connect", lambda *args, **kwargs: socket)
    assert await provider._realtime("wss://example.test", "any-model", {}, b"\0" * 3200) == "你好"
    assert [json.loads(event)["type"] for event in socket.sent] == ["session.update", "input_audio_buffer.append", "input_audio_buffer.commit", "session.finish"]
    socket = Socket(events[:-1])
    with pytest.raises(ValueError, match="ended before completion"):
        await provider._realtime("wss://example.test", "any-model", {}, b"pcm")


async def test_dashscope_8k_binary_stream_and_final_sentence(monkeypatch):
    socket = Socket(
        [
            {"header": {"event": "task-started"}},
            {"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"begin_time": 0, "sentence_end": False, "text": "中间"}}}},
            {"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"begin_time": 0, "sentence_end": True, "text": "完成"}}}},
            {"header": {"event": "task-finished"}},
        ]
    )
    monkeypatch.setattr(provider, "connect", lambda *args, **kwargs: socket)
    assert await provider._dashscope_realtime("wss://example.test", "paraformer-realtime-8k-v2", {}, b"\0" * 6400) == "完成"
    assert json.loads(socket.sent[0])["payload"]["parameters"]["sample_rate"] == 8000
    assert len(socket.sent[1]) == 3200
