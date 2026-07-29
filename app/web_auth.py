from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.config import settings
from app.database import get_session
from app.models import User, WebLoginChallenge, WebSession
from app.services.security import random_token, token_hash


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin/login", response_class=HTMLResponse)
def web_login(request: Request, session: Session = Depends(get_session)):
    browser_secret = random_token()
    challenge_id = random_token(18)[:24]
    challenge = WebLoginChallenge(
        id=challenge_id,
        browser_secret_hash=token_hash(browser_secret),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    session.add(challenge)
    session.commit()
    response = templates.TemplateResponse(
        request,
        "login.html",
        {
            "challenge_id": challenge_id,
            "qr_url": f"/admin/login/qr/{challenge_id}",
            "manual_scene": challenge_id,
        },
    )
    response.set_cookie(
        "web_login_browser",
        browser_secret,
        max_age=180,
        httponly=True,
        secure=settings.app_mode == "admin",
        samesite="strict",
    )
    return response


@router.get("/admin/login/qr/{challenge_id}")
async def web_login_qr(
    challenge_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    challenge = _browser_challenge(session, request, challenge_id)
    if _as_utc(challenge.expires_at) <= datetime.now(timezone.utc):
        return Response(status_code=410)
    if settings.wechat_qr_function_url:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                result = await client.post(
                    settings.wechat_qr_function_url,
                    json={"challenge": challenge_id},
                    headers={"X-Internal-Token": settings.internal_api_token},
                )
                result.raise_for_status()
                data = _function_payload(result.json())
                if int(data.get("statusCode", 200)) >= 400:
                    raise ValueError(str(data.get("error", "生成小程序码失败")))
                image_bytes = base64.b64decode(data["image_base64"])
                return Response(image_bytes, media_type="image/png")
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320">'
        '<rect width="320" height="320" rx="18" fill="#f3f6fa"/>'
        '<text x="160" y="120" text-anchor="middle" font-size="18" fill="#142033">开发环境登录码</text>'
        f'<text x="160" y="165" text-anchor="middle" font-size="22" font-family="monospace" fill="#0878d1">{challenge_id}</text>'
        '<text x="160" y="210" text-anchor="middle" font-size="14" fill="#5f6b7a">请在小程序中手动输入</text>'
        "</svg>"
    )
    return Response(svg, media_type="image/svg+xml", headers={"X-QR-Fallback": "true"})


@router.get("/admin/login/status/{challenge_id}")
def web_login_status(
    challenge_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> JSONResponse:
    challenge = _browser_challenge(session, request, challenge_id)
    now = datetime.now(timezone.utc)
    if _as_utc(challenge.expires_at) <= now and challenge.status in {"pending", "confirmed"}:
        challenge.status = "expired"
        session.add(challenge)
        session.commit()
    response = JSONResponse({"status": challenge.status})
    if challenge.status != "confirmed" or challenge.consumed_at is not None:
        return response
    user = session.get(User, challenge.confirmed_by_user_id)
    if user is None or user.status != "active" or user.role != "admin":
        challenge.status = "rejected"
        session.add(challenge)
        session.commit()
        return JSONResponse({"status": "rejected"})
    raw_token = random_token()
    web_session = WebSession(
        token_hash=token_hash(raw_token),
        user_id=user.id or 0,
        expires_at=now + timedelta(hours=8),
    )
    challenge.status = "consumed"
    challenge.consumed_at = now
    session.add(web_session)
    session.add(challenge)
    session.commit()
    response = JSONResponse({"status": "authenticated", "redirect": "/"})
    response.set_cookie(
        "admin_session",
        raw_token,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=settings.app_mode == "admin",
        samesite="lax",
    )
    response.delete_cookie("web_login_browser")
    return response


@router.post("/admin/logout")
def web_logout(request: Request, session: Session = Depends(get_session)) -> RedirectResponse:
    raw_token = request.cookies.get("admin_session", "")
    if raw_token:
        item = session.get(WebSession, token_hash(raw_token))
        if item is not None:
            item.revoked_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


def authenticate_web_admin(request: Request, session: Session) -> User | None:
    raw_token = request.cookies.get("admin_session", "")
    if not raw_token:
        return None
    item = session.get(WebSession, token_hash(raw_token))
    now = datetime.now(timezone.utc)
    if item is None or item.revoked_at is not None or _as_utc(item.expires_at) <= now:
        return None
    user = session.get(User, item.user_id)
    if user is None or user.status != "active" or user.role != "admin":
        return None
    return user


def _browser_challenge(session: Session, request: Request, challenge_id: str) -> WebLoginChallenge:
    challenge = session.get(WebLoginChallenge, challenge_id)
    browser_secret = request.cookies.get("web_login_browser", "")
    if challenge is None or not browser_secret or challenge.browser_secret_hash != token_hash(browser_secret):
        from app.api import ApiError

        raise ApiError(404, "CHALLENGE_NOT_FOUND", "登录请求不存在")
    return challenge


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _function_payload(data: object) -> dict:
    """兼容云函数 HTTP 网关的直接 JSON 与 body 包装响应。"""
    if not isinstance(data, dict):
        return {}
    body = data.get("body")
    if isinstance(body, str):
        try:
            import json

            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else data
        except ValueError:
            return data
    if isinstance(body, dict):
        return body
    return data
