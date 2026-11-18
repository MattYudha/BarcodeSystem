import uuid
from datetime import timedelta

from fastapi import APIRouter, Request, Response

from bhv.audit import audit
from bhv.config import get_settings
from bhv.db import execute, fetch_one, fetch_val
from bhv.deps import DB, AnyUser, client_ip
from bhv.errors import AppError
from bhv.schemas import ChangePasswordIn, LoginIn, MeOut
from bhv.security import hash_password, new_session_token, token_digest, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

LOCK_WINDOW = timedelta(minutes=15)


async def _check_rate_limit(db: DB, email: str, ip: str | None) -> None:
    s = get_settings()
    # Gagal berturut-turut untuk email ini (sejak login sukses terakhir) dalam jendela waktu.
    row = await fetch_one(
        db,
        """
        SELECT count(*) AS n, min(created_at) AS first_at, now() AS now
          FROM login_attempts
         WHERE email = :email AND NOT success
           AND created_at > now() - make_interval(mins => :win)
           AND created_at > coalesce(
                 (SELECT max(created_at) FROM login_attempts WHERE email = :email AND success),
                 '-infinity')
        """,
        email=email,
        win=int(LOCK_WINDOW.total_seconds() // 60),
    )
    assert row is not None
    if row.n >= s.login_max_failures_per_email:
        retry = int((row.first_at + LOCK_WINDOW - row.now).total_seconds()) + 1
        err = AppError("LOGIN_LOCKED", {"retry_after_seconds": max(retry, 1)})
        err.headers["Retry-After"] = str(max(retry, 1))
        raise err
    if ip:
        n_ip = await fetch_val(
            db,
            """
            SELECT count(*) FROM login_attempts
             WHERE ip = CAST(:ip AS inet) AND NOT success
               AND created_at > now() - make_interval(mins => :win)
            """,
            ip=ip,
            win=int(LOCK_WINDOW.total_seconds() // 60),
        )
        if n_ip >= s.login_max_failures_per_ip:
            err = AppError(
                "LOGIN_LOCKED", {"retry_after_seconds": int(LOCK_WINDOW.total_seconds())}
            )
            err.headers["Retry-After"] = str(int(LOCK_WINDOW.total_seconds()))
            raise err


async def _record_attempt(db: DB, email: str, ip: str | None, success: bool) -> None:
    await execute(
        db,
        "INSERT INTO login_attempts (email, ip, success) VALUES (:e, CAST(:ip AS inet), :ok)",
        e=email,
        ip=ip,
        ok=success,
    )


def _device_id(request: Request) -> uuid.UUID | None:
    raw = request.headers.get("x-device-id")
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> MeOut:
    s = get_settings()
    ip = client_ip(request)
    await _check_rate_limit(db, body.email, ip)

    user = await fetch_one(
        db,
        """SELECT id, name, email::text AS email, role::text AS role, is_active,
                  must_change_password, password_hash
             FROM users WHERE email = :e""",
        e=body.email,
    )
    ok, new_hash = verify_password(body.password, user.password_hash if user else None)
    if user is None or not ok:
        await _record_attempt(db, body.email, ip, False)
        await db.commit()
        raise AppError("INVALID_CREDENTIALS")
    if not user.is_active:
        await _record_attempt(db, body.email, ip, False)
        await db.commit()
        raise AppError("ACCOUNT_INACTIVE")

    await _record_attempt(db, body.email, ip, True)
    if new_hash:
        await execute(
            db, "UPDATE users SET password_hash = :h WHERE id = :id", h=new_hash, id=user.id
        )
    await execute(db, "UPDATE users SET last_login_at = now() WHERE id = :id", id=user.id)

    token = new_session_token()
    sid = await fetch_val(
        db,
        """
        INSERT INTO sessions (token_hash, user_id, device_id, device_label, user_agent, ip,
                              expires_at)
        VALUES (:h, :uid, :dev, :label, :ua, CAST(:ip AS inet),
                now() + make_interval(hours => :hours))
        RETURNING id::text
        """,
        h=token_digest(token),
        uid=user.id,
        dev=_device_id(request),
        label=body.device_label,
        ua=(request.headers.get("user-agent") or "")[:500] or None,
        ip=ip,
        hours=s.session_absolute_hours,
    )
    await execute(
        db,
        """INSERT INTO audit_logs (actor_id, session_id, action, entity_type, entity_id, ip)
           VALUES (:uid, CAST(:sid AS uuid), 'auth.login', 'user', :uid, CAST(:ip AS inet))""",
        uid=user.id,
        sid=sid,
        ip=ip,
    )
    await db.commit()

    response.set_cookie(
        s.cookie_name,
        token,
        max_age=s.session_absolute_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DB) -> None:
    s = get_settings()
    token = request.cookies.get(s.cookie_name)
    if token:
        await execute(
            db,
            "UPDATE sessions SET revoked_at = now() WHERE token_hash = :h AND revoked_at IS NULL",
            h=token_digest(token),
        )
        await db.commit()
    response.delete_cookie(
        s.cookie_name, path="/", secure=s.cookie_secure, httponly=True, samesite="lax"
    )


@router.get("/me", response_model=MeOut)
async def me(p: AnyUser) -> MeOut:
    return MeOut(
        id=p.user_id,
        name=p.name,
        email=p.email,
        role=p.role,
        must_change_password=p.must_change_password,
    )


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordIn, p: AnyUser, db: DB) -> None:
    current = await fetch_val(db, "SELECT password_hash FROM users WHERE id = :id", id=p.user_id)
    ok, _ = verify_password(body.current_password, current)
    if not ok:
        raise AppError("WRONG_PASSWORD")
    if body.new_password == body.current_password:
        raise AppError("PASSWORD_REUSED")
    await execute(
        db,
        """UPDATE users SET password_hash = :h, must_change_password = FALSE,
                            password_changed_at = now() WHERE id = :id""",
        h=hash_password(body.new_password),
        id=p.user_id,
    )
    # Sesi lain (perangkat lain) dicabut; sesi saat ini tetap.
    await execute(
        db,
        """UPDATE sessions SET revoked_at = now()
            WHERE user_id = :id AND revoked_at IS NULL AND id <> CAST(:sid AS uuid)""",
        id=p.user_id,
        sid=p.session_id,
    )
    await audit(db, p, "auth.change_password", "user", p.user_id)
    await db.commit()
