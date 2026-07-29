from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from app.config import settings
from app.models import Notification, NotificationSubscription, User


TEMPLATE_IDS = {
    "alert": lambda: settings.alert_template_id,
    "brief": lambda: settings.brief_template_id,
}


def template_id_for(template_type: str) -> str:
    getter = TEMPLATE_IDS.get(template_type)
    return getter() if getter else ""


def create_notification(
    session: Session,
    *,
    user_id: int,
    notification_type: str,
    title: str,
    content: str,
    page_path: str,
    idempotency_key: str,
) -> Notification:
    existing = session.exec(
        select(Notification).where(Notification.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return existing
    item = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title[:255],
        content=content,
        page_path=page_path[:500],
        idempotency_key=idempotency_key[:255],
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def record_subscription_result(
    session: Session,
    *,
    user_id: int,
    template_type: str,
    result: str,
) -> NotificationSubscription:
    if template_type not in TEMPLATE_IDS:
        raise ValueError("不支持的订阅消息类型")
    item = session.exec(
        select(NotificationSubscription).where(
            NotificationSubscription.user_id == user_id,
            NotificationSubscription.template_type == template_type,
        )
    ).first()
    if item is None:
        item = NotificationSubscription(
            user_id=user_id,
            template_type=template_type,
            template_id=template_id_for(template_type),
        )
    item.template_id = template_id_for(template_type)
    item.last_result = result[:32]
    item.updated_at = datetime.now(timezone.utc)
    if result == "accept":
        item.grant_count += 1
        blocked = session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.notification_type == template_type,
                Notification.status.in_(("no_quota", "no_template")),
            )
        ).all()
        for notification in blocked:
            notification.status = "pending"
            notification.last_error = ""
            session.add(notification)
    elif result == "ban":
        item.grant_count = 0
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def claim_pending_notifications(session: Session, limit: int = 20) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    exhausted = session.exec(
        select(Notification).where(
            Notification.status == "processing",
            Notification.claim_until < now,
            Notification.attempts >= 3,
        )
    ).all()
    for notification in exhausted:
        notification.status = "failed"
        notification.claim_until = None
        notification.last_error = notification.last_error or "发送任务超时且已达到最大重试次数"
        session.add(notification)
    if exhausted:
        session.commit()
    statement = (
        select(Notification)
        .where(
            Notification.attempts < 3,
            (Notification.status == "pending")
            | ((Notification.status == "processing") & (Notification.claim_until < now)),
        )
        .order_by(col(Notification.created_at))
        .limit(max(1, min(limit, 100)))
    )
    if session.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update(skip_locked=True)
    candidates = session.exec(statement).all()
    claimed: list[dict[str, object]] = []
    for notification in candidates:
        user = session.get(User, notification.user_id)
        subscription = session.exec(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == notification.user_id,
                NotificationSubscription.template_type == notification.notification_type,
            )
        ).first()
        template_id = template_id_for(notification.notification_type)
        if user is None or user.status != "active":
            notification.status = "failed"
            notification.last_error = "用户不存在或未启用"
        elif not template_id:
            notification.status = "no_template"
            notification.last_error = "订阅消息模板 ID 未配置"
        elif subscription is None or subscription.grant_count <= 0:
            notification.status = "no_quota"
            notification.last_error = "用户没有可用的订阅授权次数"
        else:
            notification.status = "processing"
            notification.claim_until = now + timedelta(minutes=5)
            notification.attempts += 1
            claimed.append(
                {
                    "id": notification.id,
                    "openid": user.openid,
                    "template_type": notification.notification_type,
                    "template_id": template_id,
                    "title": notification.title,
                    "content": notification.content,
                    "page": notification.page_path,
                    "created_at": _utc_isoformat(notification.created_at),
                }
            )
        session.add(notification)
    session.commit()
    return claimed


def finish_notification(
    session: Session,
    notification_id: int,
    *,
    success: bool,
    error: str = "",
    transient: bool = False,
) -> Notification | None:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.status != "processing":
        return notification
    now = datetime.now(timezone.utc)
    notification.claim_until = None
    if success:
        notification.status = "sent"
        notification.sent_at = now
        notification.last_error = ""
        subscription = session.exec(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == notification.user_id,
                NotificationSubscription.template_type == notification.notification_type,
            )
        ).first()
        if subscription is not None and subscription.grant_count > 0:
            subscription.grant_count -= 1
            subscription.updated_at = now
            session.add(subscription)
    else:
        notification.last_error = error[:2000]
        notification.status = "pending" if transient and notification.attempts < 3 else "failed"
    session.add(notification)
    session.commit()
    return notification


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
