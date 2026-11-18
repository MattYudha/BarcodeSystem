import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bhv.db import execute
from bhv.deps import Principal


def _jsonable(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)


async def audit(
    db: AsyncSession,
    actor: Principal | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
) -> None:
    """Catat audit dalam transaksi yang sama dengan perubahan datanya."""
    await execute(
        db,
        """
        INSERT INTO audit_logs (actor_id, session_id, action, entity_type, entity_id,
                                before, after, ip)
        VALUES (:actor, CAST(:sid AS uuid), :action, :etype, :eid,
                CAST(:before AS jsonb), CAST(:after AS jsonb), CAST(:ip AS inet))
        """,
        actor=actor.user_id if actor else None,
        sid=actor.session_id if actor else None,
        action=action,
        etype=entity_type,
        eid=entity_id,
        before=_jsonable(before),
        after=_jsonable(after),
        ip=ip if ip is not None else (actor.ip if actor else None),
    )
