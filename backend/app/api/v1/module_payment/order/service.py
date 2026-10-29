from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import AppCatalogPlanModel, SubscriptionModel
from app.api.v1.module_billing.service import CatalogService
from app.api.v1.module_client.user.model import ClientUserModel
from app.api.v1.module_payment.channel.model import AppPaymentChannelModel, PaymentChannelModel
from app.api.v1.module_payment.channel.service import PaymentChannelService
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.core.logger import logger

from .model import PaymentAttemptModel, PaymentCallbackModel, PaymentOrderModel
from .providers import (
    ALIPAY_QR_TIMEOUT_MINUTES,
    VerifiedAbsentOrder,
    VerifiedClosedOrder,
    VerifiedPayment,
    create_alipay_qr_order,
    create_wechat_native_order,
    query_alipay_order,
    query_wechat_order,
)
from .schema import PaymentCapability, PaymentOrderCreate, PaymentOrderOut


class PaymentOrderService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        if not auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        self.auth = auth
        self.db = db

    @staticmethod
    def _auto_renew_supported(provider: str) -> bool:
        # The first release has verified one-off payment callbacks only. Do not
        # advertise contract deduction until agreement signing and renewals exist.
        del provider
        return False

    async def capabilities(self) -> list[PaymentCapability]:
        channels = list(
            (
                await self.db.scalars(
                    select(PaymentChannelModel).where(PaymentChannelModel.provider.in_(["wechat", "alipay"]), PaymentChannelModel.is_deleted == False).order_by(PaymentChannelModel.order.asc())
                )
            ).all()
        )
        channel_service = PaymentChannelService(self.auth, self.db)
        bindings = await channel_service._app_bindings()
        return [
            PaymentCapability(
                provider=channel.provider,
                name=channel.name,
                enabled=channel.enabled and bindings.get(channel.id, False),
                configured=channel_service._to_schema(channel).configured,
                supports_auto_renew=self._auto_renew_supported(channel.provider),
            )
            for channel in channels
        ]

    def _attempt(self, order: PaymentOrderModel, action: str) -> PaymentAttemptModel:
        attempt = PaymentAttemptModel(
            app_id=order.app_id,
            order_id=order.id,
            order_no=order.order_no,
            provider=order.provider,
            action=action,
            status="started",
        )
        self.db.add(attempt)
        return attempt

    @staticmethod
    def _schedule_query(order: PaymentOrderModel, now: datetime) -> None:
        # 查询失败或未支付都保留原订单号，按次数退避，不重新向渠道下单。
        order.query_attempts = int(order.query_attempts or 0) + 1
        delays = (30, 60, 120, 300, 900, 1800, 3600)
        order.next_query_at = now + timedelta(seconds=delays[min(order.query_attempts - 1, len(delays) - 1)])

    @staticmethod
    async def query_provider(db: AsyncSession, order: PaymentOrderModel) -> VerifiedPayment | VerifiedClosedOrder | VerifiedAbsentOrder | None:
        if order.provider == "wechat":
            return await query_wechat_order(order.order_no, include_closed=True)
        channel = await db.scalar(
            select(PaymentChannelModel).where(
                PaymentChannelModel.provider == "alipay",
                PaymentChannelModel.is_deleted == False,
            )
        )
        return await query_alipay_order(order.order_no, sandbox=bool(channel and channel.mode == "sandbox"), include_closed=True)

    async def _query_and_reconcile(self, order: PaymentOrderModel) -> None:
        from .cancellation import apply_query_result, close_unpaid_order

        attempt = self._attempt(order, "query")
        paid = None
        try:
            paid = await self.query_provider(self.db, order)
        except CustomException as exc:
            attempt.status = "failed"
            attempt.error_message = exc.msg[:500]
            logger.warning(
                "支付主动查单失败: provider={}, order_no={}, reason={}",
                order.provider,
                order.order_no,
                exc.msg,
            )
        except Exception:
            attempt.status = "failed"
            attempt.error_message = "支付渠道查单请求异常"
            logger.exception(
                "支付主动查单异常: provider={}, order_no={}",
                order.provider,
                order.order_no,
            )
        else:
            terminal = await apply_query_result(self.db, order, paid)
            attempt.status = order.status if terminal else "not_paid"
        completed_at = datetime.now(UTC)
        attempt.completed_at = completed_at
        order.updated_time = completed_at
        if order.status not in {"paid", "closed"}:
            expires_at = order.expires_at.replace(tzinfo=UTC) if order.expires_at.tzinfo is None else order.expires_at
            if expires_at <= completed_at or order.cancel_requested_at:
                await close_unpaid_order(self.db, order)
            else:
                self._schedule_query(order, completed_at)
        await self.db.flush()

    async def cancel(self, order_no: str, reason: str = "用户取消购买") -> PaymentOrderOut:
        from app.api.v1.module_finance.common import audit
        from app.api.v1.module_growth.service import lock_app

        from .cancellation import close_unpaid_order

        # Same lock order as checkout/callback, preventing payment/cancel races.
        await lock_app(self.db, self.auth.app_id)
        statement = select(PaymentOrderModel).where(PaymentOrderModel.app_id == self.auth.app_id, PaymentOrderModel.order_no == order_no, PaymentOrderModel.is_deleted == False)
        if self.auth.actor_type == "client":
            statement = statement.where(PaymentOrderModel.user_id == self.auth.user.id)
        order = await self.db.scalar(statement.with_for_update().execution_options(populate_existing=True))
        if not order:
            raise CustomException(msg="订单不存在", status_code=404)
        before = order.status
        if order.status not in {"paid", "closed"} and order.paid_at is None:
            await close_unpaid_order(self.db, order)
            audit(
                self.db,
                order.app_id,
                "order",
                order.id,
                "close",
                None if self.auth.actor_type == "client" else self.auth.user.id,
                reason,
                {"status": before},
                {"status": order.status, "requested_by": self.auth.actor_type, "user_id": self.auth.user.id},
            )
            await self.db.flush()
        return PaymentOrderOut.model_validate(order)

    async def create(self, data: PaymentOrderCreate) -> PaymentOrderOut:
        from app.api.v1.module_billing.mode_switch.service import confirm_for_order, fulfill_paid_order
        from app.api.v1.module_client.app.model_policy import allowed_modes, billing_user, current_mode, get_model_policy

        app_policy = await get_model_policy(self.db, self.auth.app_id, lock=True)
        # 对同一用户串行化幂等键检查与插入，避免并发请求同时向渠道下单。
        user_id = await self.db.scalar(
            select(ClientUserModel.id).where(ClientUserModel.app_id == self.auth.app_id, ClientUserModel.id == self.auth.user.id, ClientUserModel.is_deleted == False).with_for_update()
        )
        if user_id is None:
            raise CustomException(msg="客户端用户不存在", status_code=401)
        existing = await self.db.scalar(
            select(PaymentOrderModel).where(
                PaymentOrderModel.app_id == self.auth.app_id,
                PaymentOrderModel.user_id == self.auth.user.id,
                PaymentOrderModel.idempotency_key == data.idempotency_key,
            )
        )
        if existing:
            if existing.is_deleted:
                raise CustomException(msg="该购买编号对应已删除订单，请使用新的购买编号重新下单", status_code=409)
            if (existing.catalog_plan_id, existing.provider, existing.auto_renew_requested, existing.replaces_order_no) != (
                data.catalog_plan_id,
                data.provider,
                data.auto_renew,
                data.replaces_order_no,
            ):
                raise CustomException(msg="该请求编号已用于不同的套餐或支付方式", status_code=409)
            if data.mode_switch_confirmation and existing.plan_snapshot.get("mode_version") != data.mode_switch_confirmation.expected_mode_version:
                raise CustomException(msg="该请求编号已用于另一版本的模式切换，请继续查询原订单", status_code=409)
            return PaymentOrderOut.model_validate(existing)
        now = datetime.now(UTC)
        plan = await self.db.scalar(
            select(AppCatalogPlanModel).where(
                AppCatalogPlanModel.id == data.catalog_plan_id,
                AppCatalogPlanModel.app_id == self.auth.app_id,
                AppCatalogPlanModel.status == "on_sale",
                AppCatalogPlanModel.is_deleted == False,
                or_(AppCatalogPlanModel.effective_from.is_(None), AppCatalogPlanModel.effective_from <= now),
                or_(AppCatalogPlanModel.effective_until.is_(None), AppCatalogPlanModel.effective_until > now),
            )
        )
        if not plan:
            raise CustomException(msg="该套餐当前不可购买")
        if plan.entitlement_kind not in allowed_modes(app_policy):
            raise CustomException(msg="客户端模型模式已变更，请刷新套餐后重试", status_code=409)
        user = await billing_user(self.db, app_policy, self.auth.user.id, lock=True)
        target_change = current_mode(app_policy, user) != plan.entitlement_kind
        switching = await self.db.scalar(
            select(PaymentOrderModel.id)
            .where(
                PaymentOrderModel.app_id == app_policy.id,
                PaymentOrderModel.user_id == user.id,
                PaymentOrderModel.mode_switch["status"].as_string() == "requires_confirmation",
                or_(PaymentOrderModel.status == "paid", PaymentOrderModel.paid_at.is_not(None)),
                PaymentOrderModel.replaced_by_order_no.is_(None),
                PaymentOrderModel.is_deleted == False,
            )
            .limit(1)
        )
        if switching:
            raise CustomException(msg="存在已收款但权益待财务核对的订单，请先联系运营处理", status_code=409)
        replaced_order = None
        if data.replaces_order_no:
            replaced_order = await self.db.scalar(
                select(PaymentOrderModel)
                .where(PaymentOrderModel.app_id == self.auth.app_id, PaymentOrderModel.user_id == user.id, PaymentOrderModel.order_no == data.replaces_order_no, PaymentOrderModel.is_deleted == False)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not replaced_order:
                raise CustomException(msg="未找到可更换的本人原订单", status_code=404)
            if replaced_order.status == "paid" or replaced_order.paid_at or replaced_order.provider_trade_no:
                raise CustomException(msg="原订单已收款，请刷新权益；再次购买应创建独立的新购买", status_code=409)
            if replaced_order.replaced_by_order_no:
                raise CustomException(msg="原订单已被更换，请查询原订单中的 replaced_by_order_no 后继续", status_code=409)
        reset_authorized = await confirm_for_order(self.db, app_policy, user, plan, data.mode_switch_confirmation)
        if plan.entitlement_kind == "duration" and data.auto_renew:
            raise CustomException(msg="时长套餐暂不支持自动扣款续费", status_code=422)
        from app.api.v1.module_agreement.public_service import PublicAgreementService

        agreements = PublicAgreementService(self.db, self.auth.app_id)
        agreement_scene = await agreements.validate("credit_purchase" if plan.plan_type == "credit_pack" else "membership_purchase", data.agreement_acceptance)
        subscription = await self.db.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.app_id == self.auth.app_id,
                SubscriptionModel.user_id == self.auth.user.id,
                SubscriptionModel.is_deleted == False,
            )
        )
        active_subscription = bool(
            subscription
            and subscription.entitlement_kind == plan.entitlement_kind
            and subscription.status == "active"
            and (subscription.current_period_end.replace(tzinfo=UTC) if subscription.current_period_end.tzinfo is None else subscription.current_period_end) > now
        )
        if plan.plan_type == "credit_pack" and plan.requires_active_subscription and not active_subscription:
            raise CustomException(msg="流量积分包仅限有效订阅用户购买", status_code=403)
        purchase_type = CatalogService.purchase_type_for_plan(plan, subscription)
        base_price = plan.recurring_price_fen if purchase_type == "renewal" else plan.one_time_price_fen
        pricing = await CatalogService(self.auth, self.db).resolve_pricing(plan.id, purchase_type, now=now, user_id=self.auth.user.id)
        amount = int(pricing["execution_price_fen"])
        if plan.entitlement_kind == "duration" and amount <= 0:
            raise CustomException(msg="时长套餐执行价必须大于0", status_code=422)
        strategy_snapshot = {
            "strategy_id": pricing.get("strategy_id"),
            "strategy_item_id": pricing.get("strategy_item_id"),
            "version": pricing.get("strategy_version"),
            "name": pricing.get("strategy_name"),
            "scope_type": pricing.get("scope_type"),
            "discount_rate": pricing["discount_rate"],
            "execution_price_fen": amount,
            "margin_rate": pricing["margin_rate"],
            "allowed_cost_yuan": pricing["allowed_cost_yuan"],
            "credits_per_cost_yuan": pricing["credits_per_cost_yuan"],
        }
        channel = await self.db.scalar(
            select(PaymentChannelModel)
            .join(
                AppPaymentChannelModel,
                AppPaymentChannelModel.channel_id == PaymentChannelModel.id,
            )
            .where(
                PaymentChannelModel.provider == data.provider,
                PaymentChannelModel.enabled == True,
                PaymentChannelModel.is_deleted == False,
                AppPaymentChannelModel.app_id == self.auth.app_id,
                AppPaymentChannelModel.enabled == True,
                AppPaymentChannelModel.is_deleted == False,
            )
        )
        if amount > 0:
            if not channel or not PaymentChannelService(self.auth, self.db)._to_schema(channel).configured:
                raise CustomException(msg="所选支付渠道暂不可用", status_code=503)
            if data.auto_renew and not self._auto_renew_supported(data.provider):
                raise CustomException(msg="当前支付渠道尚未开通自动续费能力")
        plan_snapshot = {
            "entitlement_kind": plan.entitlement_kind,
            "mode_version": user.mode_version,
            "service_mode": app_policy.service_mode,
            "platform_model_enabled": app_policy.platform_model_enabled,
            "model_policy_version": app_policy.model_policy_version,
            "id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "tier_order": plan.tier_order,
            "tier_code": plan.tier_code,
            "plan_type": plan.plan_type,
            "requires_active_subscription": plan.requires_active_subscription,
            "benefit_period_days": plan.benefit_period_days,
            "total_credits": plan.total_credits,
            "release_plan": plan.release_plan,
            "credit_valid_days": plan.credit_valid_days,
            "benefits": plan.benefits,
            "base_price_fen": base_price,
            "execution_price_fen": amount,
            "credits_per_cost_yuan": pricing["credits_per_cost_yuan"],
            "pricing_snapshot": strategy_snapshot,
        }
        order = PaymentOrderModel(
            app_id=self.auth.app_id,
            user_id=self.auth.user.id,
            order_no=f"YX{now.strftime('%Y%m%d%H%M%S')}{uuid4().hex[:10].upper()}",
            idempotency_key=data.idempotency_key,
            replaces_order_no=data.replaces_order_no,
            catalog_plan_id=plan.id,
            purchase_type=purchase_type,
            provider=data.provider,
            amount_fen=amount,
            currency="CNY",
            plan_snapshot=plan_snapshot,
            strategy_snapshot=strategy_snapshot,
            status="created",
            expires_at=now + timedelta(minutes=15),
            auto_renew_requested=data.auto_renew,
        )
        self.db.add(order)
        await self.db.flush()
        if target_change:
            order.mode_switch = {
                "id": order.order_no,
                "source_mode": current_mode(app_policy, user),
                "target_mode": plan.entitlement_kind,
                "status": "pending_payment",
                "reset_authorized": reset_authorized is True,
            }
        await agreements.record(agreement_scene, self.auth.user.id, f"order:{order.order_no}", data.agreement_acceptance)
        if amount == 0:
            order.status = "paid"
            order.paid_at = now
            await fulfill_paid_order(self.db, order)
        else:
            attempt = self._attempt(order, "create")
            try:
                if data.provider == "wechat":
                    if channel and channel.mode == "sandbox":
                        raise CustomException(msg="微信支付 APIv3 不提供通用沙箱下单，请改用生产商户的测试金额")
                    order.pay_url = await create_wechat_native_order(order.order_no, amount, plan.name)
                else:
                    order.pay_url = await create_alipay_qr_order(
                        order.order_no,
                        amount,
                        plan.name,
                        sandbox=bool(channel and channel.mode == "sandbox"),
                    )
                    order.strategy_snapshot = {
                        **(order.strategy_snapshot or {}),
                        "payment_session": {"kind": "alipay_precreate", "qr_expires_at": (datetime.now(UTC) + timedelta(minutes=ALIPAY_QR_TIMEOUT_MINUTES)).isoformat()},
                    }
                order.status = "pending"
                order.next_query_at = datetime.now(UTC) + timedelta(seconds=30)
                attempt.status = "success"
            except CustomException as exc:
                # 渠道或网络错误无法证明订单未创建；服务端错误先查原订单号。
                order.status = "confirming" if exc.status_code >= 500 else "failed"
                order.failure_reason = exc.msg[:500]
                attempt.status = "failed"
                attempt.error_message = exc.msg[:500]
                if order.status == "confirming":
                    order.next_query_at = datetime.now(UTC) + timedelta(seconds=30)
            except Exception:
                order.status = "confirming"
                order.failure_reason = "支付渠道下单结果待确认，请勿重复付款"
                attempt.status = "failed"
                attempt.error_message = "支付渠道请求异常"
                order.next_query_at = datetime.now(UTC) + timedelta(seconds=30)
                logger.exception(
                    "支付下单异常: provider={}, order_no={}",
                    data.provider,
                    order.order_no,
                )
            attempt.completed_at = datetime.now(UTC)
        await self.db.flush()
        if order.status == "failed" and order.mode_switch:
            order.mode_switch = {**order.mode_switch, "status": "failed", "message": "支付未完成，原模式权益保持不变"}
            await self.db.flush()
        if replaced_order and order.status != "failed":
            from app.api.v1.module_finance.common import audit

            replaced_order.replaced_by_order_no = order.order_no
            replaced_order.cancel_requested_at = replaced_order.cancel_requested_at or datetime.now(UTC)
            replaced_order.pay_url = None
            if replaced_order.status != "closed":
                replaced_order.next_query_at = datetime.now(UTC)
            audit(
                self.db, order.app_id, "order", replaced_order.id, "replace_checkout", None, "用户更换套餐或支付渠道，原单继续核验和关单，不阻塞新购买", after={"replaced_by_order_no": order.order_no}
            )
            await self.db.flush()
        return PaymentOrderOut.model_validate(order)

    async def get(self, order_no: str) -> PaymentOrderOut:
        from app.api.v1.module_growth.service import lock_app

        await lock_app(self.db, self.auth.app_id)
        order = await self.db.scalar(
            select(PaymentOrderModel)
            .where(
                PaymentOrderModel.order_no == order_no,
                PaymentOrderModel.app_id == self.auth.app_id,
                PaymentOrderModel.user_id == self.auth.user.id,
                PaymentOrderModel.is_deleted == False,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not order:
            raise CustomException(msg="订单不存在", status_code=404)
        now = datetime.now(UTC)
        updated_time = order.updated_time
        if updated_time.tzinfo is None:
            updated_time = updated_time.replace(tzinfo=UTC)
        next_query_at = order.next_query_at
        if next_query_at and next_query_at.tzinfo is None:
            next_query_at = next_query_at.replace(tzinfo=UTC)
        query_due = next_query_at <= now if next_query_at else updated_time <= now - timedelta(seconds=10)
        if order.status in {"created", "pending", "confirming", "failed"} and query_due:
            await self._query_and_reconcile(order)
        expires_at = order.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if order.status in {"created", "pending"} and expires_at <= datetime.now(UTC):
            # 等待下一次渠道核验，不能只凭本地过期判定关单成功。
            order.status = "confirming"
            await self.db.flush()
        return PaymentOrderOut.model_validate(order)

    async def list_admin(self, entitlement_kind: str | None = None) -> list[PaymentOrderOut]:
        rows = list(
            (
                await self.db.scalars(
                    select(PaymentOrderModel)
                    .where(
                        PaymentOrderModel.app_id == self.auth.app_id,
                        PaymentOrderModel.is_deleted == False,
                        *([func.coalesce(PaymentOrderModel.plan_snapshot["entitlement_kind"].as_string(), "credits") == entitlement_kind] if entitlement_kind else []),
                    )
                    .order_by(PaymentOrderModel.id.desc())
                    .limit(500)
                )
            ).all()
        )
        return [PaymentOrderOut.model_validate(row) for row in rows]


class PaymentCallbackService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _check_duplicate(callback: PaymentCallbackModel | None, paid: VerifiedPayment) -> bool:
        if callback is None:
            return False
        if (callback.order_no, callback.provider_trade_no, callback.amount_fen) != (paid.order_no, paid.provider_trade_no, paid.amount_fen):
            raise CustomException(msg="支付通知编号关联了不同交易", status_code=409)
        return True

    async def process(self, provider: str, paid: VerifiedPayment) -> None:
        duplicate = await self.db.scalar(
            select(PaymentCallbackModel).where(
                PaymentCallbackModel.provider == provider,
                PaymentCallbackModel.callback_id == paid.callback_id,
            )
        )
        if self._check_duplicate(duplicate, paid):
            return
        from app.api.v1.module_growth.service import lock_app

        scope = await self.db.scalar(select(PaymentOrderModel.app_id).where(PaymentOrderModel.order_no == paid.order_no))
        if scope:
            await lock_app(self.db, scope)
        order = await self.db.scalar(select(PaymentOrderModel).where(PaymentOrderModel.order_no == paid.order_no).with_for_update())
        # A duplicate request can pass the optimistic check while the first
        # transaction is still waiting for this order lock. Recheck after the
        # lock so only one transaction writes the callback and activates rights.
        duplicate = await self.db.scalar(
            select(PaymentCallbackModel).where(
                PaymentCallbackModel.provider == provider,
                PaymentCallbackModel.callback_id == paid.callback_id,
            )
        )
        if self._check_duplicate(duplicate, paid):
            return
        callback = PaymentCallbackModel(
            provider=provider,
            callback_id=paid.callback_id,
            order_no=paid.order_no,
            provider_trade_no=paid.provider_trade_no,
            amount_fen=paid.amount_fen,
            payload_digest=paid.payload_digest,
            status="received",
        )
        self.db.add(callback)
        if not order or order.provider != provider or order.amount_fen != paid.amount_fen:
            callback.status = "rejected"
            callback.failure_reason = "订单不存在、渠道不匹配或金额不一致"
            await self.db.flush()
            raise CustomException(msg="支付回调与订单不匹配", status_code=400)
        if not paid.provider_trade_no or (order.provider_trade_no and order.provider_trade_no != paid.provider_trade_no):
            raise CustomException(msg="渠道交易号与订单不匹配", status_code=409)
        other_order = await self.db.scalar(
            select(PaymentOrderModel.id).where(
                PaymentOrderModel.provider == provider,
                PaymentOrderModel.provider_trade_no == paid.provider_trade_no,
                PaymentOrderModel.id != order.id,
            )
        )
        if other_order:
            raise CustomException(msg="渠道交易号已关联其他订单", status_code=409)
        from app.api.v1.module_client.app.model_policy import order_matches_model_policy

        matches_mode = await order_matches_model_policy(self.db, order.app_id, order.plan_snapshot)
        if order.is_deleted:
            from app.api.v1.module_finance.common import audit

            order.is_deleted = False
            order.deleted_time = None
            audit(self.db, order.app_id, "order", order.id, "restore_paid", None, "已删除订单收到验签付款，恢复原订单并核对权益")
        if order.status != "paid":
            order.status = "paid"
            order.paid_at = paid.paid_at or datetime.now(UTC)
            order.closed_at = None
            order.failure_reason = None
            order.pay_url = None
            order.provider_trade_no = paid.provider_trade_no
            order.next_query_at = None
            if order.mode_switch and order.mode_switch.get("status") == "cancelled":
                order.mode_switch = {**order.mode_switch, "status": "requires_confirmation", "message": "关单后收到已验签付款，待财务核对或退款，原模式与权益保持不变"}
            from app.api.v1.module_billing.mode_switch.service import fulfill_paid_order

            matches_mode = await fulfill_paid_order(self.db, order)
        elif not order.provider_trade_no:
            # 兼容早期已支付但未保存渠道交易号的记录。
            order.provider_trade_no = paid.provider_trade_no
        callback.status = "processed"
        from app.api.v1.module_growth.reward_service import RewardService

        if matches_mode and (not order.mode_switch or order.mode_switch.get("status") == "completed"):
            await RewardService(self.db, order.app_id).paid_order(order)
        callback.verified_at = datetime.now(UTC)
        await self.db.flush()
