"""One monotonic deadline across preparation, candidates and streamed reads."""

import asyncio
import time
from contextlib import asynccontextmanager


class GenerationDeadlineExceeded(TimeoutError):
    before_await = True


async def within_deadline(factory, prepared):
    settings = prepared.generation_settings
    if settings is None:
        return await factory()
    remaining = prepared.started_at + settings.total_timeout_seconds - time.perf_counter()
    if remaining <= 0:
        raise GenerationDeadlineExceeded("Generation total deadline reached")
    async with asyncio.timeout(remaining):
        return await factory()


@asynccontextmanager
async def bounded_stream(context, prepared):
    response = await within_deadline(context.__aenter__, prepared)
    try:
        yield response
    finally:
        # Closing is outside the generation deadline, within the settlement
        # margin. No timeout context spans a yield into the ASGI caller.
        if prepared.generation_settings is None:
            await context.__aexit__(None, None, None)
        else:
            async with asyncio.timeout(10):
                await context.__aexit__(None, None, None)


async def bounded_lines(lines, prepared):
    iterator = aiter(lines)
    while True:
        try:
            line = await within_deadline(lambda: anext(iterator), prepared)
        except StopAsyncIteration:
            return
        yield line
