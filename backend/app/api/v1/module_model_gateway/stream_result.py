"""收集完整流式结果供持久化重放；不把中断的流伪装为成功。"""

import json

from .schema import RuntimeCompletionOut


class StreamResult:
    def __init__(self):
        self.content = []
        self.reasoning = []
        self.calls = {}

    def append(self, content, reasoning, calls):
        if content:
            self.content.append(content)
        if reasoning:
            self.reasoning.append(reasoning)
        for part in calls:
            index = part.get("index", 0)
            call = self.calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if part.get("id"):
                call["id"] = part["id"]
            if part.get("type"):
                call["type"] = part["type"]
            for field in ("name", "arguments"):
                call["function"][field] += part.get("function", {}).get(field) or ""

    def result(self, **kwargs):
        return RuntimeCompletionOut(content="".join(self.content), reasoning_content="".join(self.reasoning), tool_calls=list(self.calls.values()), **kwargs)


def sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def result_events(result, *, replay=False):
    if replay:
        if result.content:
            yield sse("text_delta", {"delta": result.content})
        if result.reasoning_content:
            yield sse("reasoning_delta", {"delta": result.reasoning_content})
        if result.tool_calls:
            yield sse("tool_call", {"tool_calls": [dict(call, index=i) for i, call in enumerate(result.tool_calls)]})
    yield sse("usage", {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "charged_credits": result.charged_credits, "settlement_status": result.settlement_status})
    yield sse(
        "done",
        {
            "request_id": result.request_id,
            "model": result.model,
            "finish_reason": result.finish_reason,
            "effective_max_output_tokens": result.effective_max_output_tokens,
            "generation_settings": result.generation_settings.model_dump() if result.generation_settings else None,
            "generation_policy_status": result.generation_policy_status,
            "settlement_status": result.settlement_status,
        },
    )
