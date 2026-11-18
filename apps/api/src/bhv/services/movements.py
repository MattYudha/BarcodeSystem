"""Penulisan transaksi stok. Validasi stok/arsip/pembatalan final ada di trigger DB;
modul ini hanya menyusun baris dalam satu transaksi DB (dipakai stok awal, scan, opname)."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from bhv.db import execute, fetch_one
from bhv.deps import Principal

MovementType = Literal["IN", "OUT", "ADJUST", "REVERSAL"]
Source = Literal["scanner", "camera", "manual", "initial", "opname"]


@dataclass(frozen=True)
class Line:
    variant_id: int
    qty: int  # sudah bertanda: IN > 0, OUT < 0
    reason: str | None = None
    production_date: date | None = None
    batch_code: str | None = None
    note: str | None = None
    source: Source = "manual"
    reversal_of: int | None = None
    opname_id: int | None = None


def request_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def insert_group(
    db: AsyncSession,
    actor: Principal,
    kind: MovementType,
    lines: list[Line],
    *,
    group_id: uuid.UUID | None = None,
    req_hash: str | None = None,
) -> tuple[uuid.UUID, list[int]]:
    """Insert movement_group + semua baris. Baris diurutkan variant_id agar urutan lock
    konsisten antar transaksi paralel (mencegah deadlock). Return (group_id, movement_ids)."""
    assert lines, "minimal satu baris"
    gid = group_id or uuid.uuid4()
    await execute(
        db,
        """
        INSERT INTO movement_groups (id, kind, request_hash, line_count, user_id, session_id)
        VALUES (:id, CAST(:kind AS movement_type), :h, :n, :uid, CAST(:sid AS uuid))
        """,
        id=gid,
        kind=kind,
        h=req_hash or request_hash([line.__dict__ for line in lines]),
        n=len(lines),
        uid=actor.user_id,
        sid=actor.session_id,
    )
    ids: list[int] = []
    for line in sorted(lines, key=lambda x: x.variant_id):
        row = await fetch_one(
            db,
            """
            INSERT INTO stock_movements
              (group_id, variant_id, type, qty, reason, production_date, batch_code, note,
               reversal_of, opname_id, source, user_id, session_id)
            VALUES
              (:gid, :vid, CAST(:type AS movement_type), :qty, CAST(:reason AS out_reason),
               :pdate, :batch, :note, :rev, :opname, CAST(:source AS movement_source),
               :uid, CAST(:sid AS uuid))
            RETURNING id
            """,
            gid=gid,
            vid=line.variant_id,
            type=kind,
            qty=line.qty,
            reason=line.reason,
            pdate=line.production_date,
            batch=line.batch_code,
            note=line.note,
            rev=line.reversal_of,
            opname=line.opname_id,
            source=line.source,
            uid=actor.user_id,
            sid=actor.session_id,
        )
        assert row is not None
        ids.append(int(row.id))
    return gid, ids
