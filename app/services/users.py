from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import settings
from app.models import User, UserPreference, UserSecret
from app.schemas import RuntimeConfig
from app.services.security import SecretCipher


DEEPSEEK_SECRET_KIND = "deepseek_api_key"


def get_or_create_user(session: Session, openid: str, display_name: str = "") -> User:
    user = session.exec(select(User).where(User.openid == openid)).first()
    now = datetime.now(timezone.utc)
    is_bootstrap_admin = openid in settings.admin_openids
    if user is None:
        user = User(
            openid=openid,
            display_name=display_name.strip(),
            status="active" if is_bootstrap_admin else "pending",
            role="admin" if is_bootstrap_admin else "user",
            approved_at=now if is_bootstrap_admin else None,
            last_seen_at=now,
        )
        session.add(user)
        try:
            session.commit()
            session.refresh(user)
        except IntegrityError:
            session.rollback()
            user = session.exec(select(User).where(User.openid == openid)).first()
            if user is None:
                raise
    else:
        user.last_seen_at = now
        if display_name.strip():
            user.display_name = display_name.strip()
        if is_bootstrap_admin:
            user.status = "active"
            user.role = "admin"
            user.approved_at = user.approved_at or now
        session.add(user)
    session.commit()
    get_preference(session, user.id or 0)
    return user


def get_preference(session: Session, user_id: int) -> UserPreference:
    preference = session.get(UserPreference, user_id)
    if preference is None:
        preference = UserPreference(user_id=user_id, deepseek_model=settings.deepseek_model)
        session.add(preference)
        try:
            session.commit()
            session.refresh(preference)
        except IntegrityError:
            session.rollback()
            preference = session.get(UserPreference, user_id)
            if preference is None:
                raise
    return preference


def set_deepseek_key(session: Session, user_id: int, api_key: str) -> None:
    value = api_key.strip()
    existing = session.exec(
        select(UserSecret).where(UserSecret.user_id == user_id, UserSecret.kind == DEEPSEEK_SECRET_KIND)
    ).first()
    if not value:
        if existing is not None:
            session.delete(existing)
            session.commit()
        return
    encrypted = SecretCipher().encrypt(value, user_id=user_id, kind=DEEPSEEK_SECRET_KIND)
    if existing is None:
        existing = UserSecret(
            user_id=user_id,
            kind=DEEPSEEK_SECRET_KIND,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
        )
    else:
        existing.ciphertext = encrypted.ciphertext
        existing.nonce = encrypted.nonce
        existing.key_version = encrypted.key_version
        existing.updated_at = datetime.now(timezone.utc)
    session.add(existing)
    session.commit()


def has_deepseek_key(session: Session, user_id: int) -> bool:
    return session.exec(
        select(UserSecret.id).where(UserSecret.user_id == user_id, UserSecret.kind == DEEPSEEK_SECRET_KIND)
    ).first() is not None


def user_runtime_config(session: Session, user_id: int) -> RuntimeConfig:
    preference = get_preference(session, user_id)
    model = preference.deepseek_model
    if model not in settings.allowed_deepseek_models:
        model = settings.deepseek_model
    secret = session.exec(
        select(UserSecret).where(UserSecret.user_id == user_id, UserSecret.kind == DEEPSEEK_SECRET_KIND)
    ).first()
    api_key = ""
    if secret is not None:
        api_key = SecretCipher().decrypt(
            secret.ciphertext,
            secret.nonce,
            user_id=user_id,
            kind=secret.kind,
            key_version=secret.key_version,
        )
    return RuntimeConfig(
        deepseek_api_key=api_key,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model=model,
    )


def system_runtime_config(session: Session) -> RuntimeConfig:
    admin = session.exec(
        select(User).where(User.status == "active", User.role == "admin").order_by(User.id)
    ).first()
    if admin is not None and admin.id is not None and has_deepseek_key(session, admin.id):
        return user_runtime_config(session, admin.id)
    return RuntimeConfig(
        deepseek_api_key=settings.deepseek_api_key,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model=settings.deepseek_model,
    )
