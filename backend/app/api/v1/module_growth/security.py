"""Shared account-level throttling for password-confirmed asset operations."""

from app.core.exceptions import CustomException


async def sensitive_rate_limit(redis, app_id: int, user_id: int) -> None:
    try:
        # The counter lives outside the business transaction, including failed passwords.
        key = f"growth:asset-confirm:{app_id}:{user_id}"
        async with redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, 300)
            count, _ = await pipeline.execute()
    except Exception as exc:
        raise CustomException(msg="安全验证服务暂不可用，请稍后重试", status_code=503) from exc
    if int(count) > 10:
        raise CustomException(msg="操作过于频繁，请5分钟后重试", status_code=429)
