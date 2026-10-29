"""Read authenticated merchant bills; never extract archives onto the filesystem."""

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

from app.api.v1.module_payment.order.providers import _wechat_request_headers
from app.core.exceptions import CustomException

from .gateway import alipay_request, wechat_request

MAX_BILL_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class BillLine:
    order_no: str
    trade_no: str
    refund_no: str
    kind: str
    amount: int
    fee: int | None


def cents(value: str) -> int:
    try:
        amount = Decimal(value.strip().lstrip("`")) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError
        return int(amount)
    except (InvalidOperation, ValueError):
        raise CustomException(msg="账单金额格式异常，未写入对账结果", status_code=422) from None


def parse_csv(content: bytes, provider: str) -> list[BillLine]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gb18030")
    rows = list(csv.reader(io.StringIO(text)))
    header_at = next((i for i, row in enumerate(rows) if any(c.strip().lstrip("`") in ("商户订单号", "商家订单号") for c in row)), None)
    if header_at is None:
        raise CustomException(msg="账单缺少商户订单号列，请核对交易明细格式", status_code=422)
    headers = [c.strip().lstrip("`") for c in rows[header_at]]
    result = []
    for raw in rows[header_at + 1 :]:
        if not raw or raw[0].lstrip().startswith("#"):
            continue
        if len(raw) != len(headers):
            # Summary rows have a separate shorter header at the end of the official bill.
            if raw[0].strip().lstrip("`").startswith(("总", "合计")):
                break
            raise CustomException(msg="账单明细列数异常，未忽略不完整交易", status_code=422)
        row = dict(zip(headers, (v.strip().lstrip("`") for v in raw), strict=True))
        order = row.get("商户订单号") or row.get("商家订单号")
        if not order:
            raise CustomException(msg="账单明细缺少订单号", status_code=422)
        if provider == "alipay":
            kind = row.get("业务类型", "")
            if kind not in ("交易", "退款"):
                raise CustomException(msg="支付宝账单存在尚未识别的业务类型，请人工核对", status_code=422)
            amount = row.get("订单金额（元）", row.get("订单金额(元)", ""))
            fee = row.get("服务费（元）", row.get("服务费(元)"))
            result.append(
                BillLine(
                    order, row.get("支付宝交易号", ""), row.get("商家退款单号", row.get("退款批次号", "")), "refund" if kind == "退款" else "payment", abs(cents(amount)), cents(fee) if fee else None
                )
            )
        else:
            state = row.get("交易状态")
            if state not in ("SUCCESS", "REFUND"):
                raise CustomException(msg="微信账单存在尚未识别的交易状态，请人工核对", status_code=422)
            amount = row.get("申请退款金额", row.get("退款金额", "")) if state == "REFUND" else row.get("订单金额", row.get("总金额", ""))
            result.append(
                BillLine(
                    order, row.get("微信订单号", ""), row.get("商户退款单号", ""), "refund" if state == "REFUND" else "payment", abs(cents(amount)), cents(row["手续费"]) if row.get("手续费") else None
                )
            )
    return result


def parse_bill(content: bytes, provider: str) -> list[BillLine]:
    if len(content) > MAX_BILL_BYTES:
        raise CustomException(msg="账单超过单次处理上限", status_code=413)
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return parse_csv(content, provider)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        files = [f for f in archive.infolist() if not f.is_dir() and f.filename.lower().endswith(".csv") and "汇总" not in f.filename]
        if not files or len(files) > 20 or sum(f.file_size for f in files) > MAX_BILL_BYTES:
            raise CustomException(msg="账单压缩包格式或大小异常", status_code=422)
        return [line for f in files for line in parse_csv(archive.read(f), provider)]


async def download_bill(provider: str, day: date) -> tuple[bytes, str]:
    expected_hash = None
    if provider == "alipay":
        data = await alipay_request("alipay.data.dataservice.bill.downloadurl.query", {"bill_type": "trade", "bill_date": day.isoformat(), "secure": "true"})
        if data.get("code") != "10000":
            raise CustomException(msg=f"支付宝账单暂不可用（{data.get('sub_code') or data.get('code')}），请确认日期、账单权限及是否有交易", status_code=409)
        url = data.get("bill_download_url", "")
    else:
        status, data = await wechat_request("GET", f"/v3/bill/tradebill?bill_date={day.isoformat()}&bill_type=ALL")
        if status != 200:
            raise CustomException(msg=f"微信账单暂不可用（{data.get('code')}），请确认日期、账单权限及是否有交易", status_code=409)
        url, expected_hash = data.get("download_url", ""), data.get("hash_value")
        if data.get("hash_type") != "SHA1" or not expected_hash:
            raise CustomException(msg="微信账单未返回可校验的摘要", status_code=502)
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    allowed = host == "api.mch.weixin.qq.com" if provider == "wechat" else host.endswith(".alipay.com") or host.endswith(".alipayobjects.com")
    if parsed.scheme != "https" or not allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise CustomException(msg="渠道账单下载地址未通过校验", status_code=502)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    headers = _wechat_request_headers("GET", target) if provider == "wechat" else {}
    chunks, size = [], 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client, client.stream("GET", url, headers=headers) as response:
        if response.status_code != 200:
            raise CustomException(msg="账单文件下载失败，请重试", status_code=502)
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BILL_BYTES:
                raise CustomException(msg="账单超过单次处理上限", status_code=413)
            chunks.append(chunk)
    content = b"".join(chunks)
    if expected_hash and hashlib.sha1(content).hexdigest().lower() != expected_hash.lower():
        raise CustomException(msg="微信账单摘要不匹配，未写入任何对账结果", status_code=502)
    return content, hashlib.sha256(content).hexdigest()
