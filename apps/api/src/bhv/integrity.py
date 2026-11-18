"""Rekonsiliasi stok: cache `product_variants.stock` harus sama dengan Σqty dan saldo terakhir.

Dipakai oleh CLI `bhv check-stock` dan test suite.
"""

from dataclasses import dataclass

import psycopg

STOCK_MISMATCH_SQL = """
WITH agg AS (
  SELECT variant_id, sum(qty)::bigint AS total FROM stock_movements GROUP BY variant_id
), last AS (
  SELECT DISTINCT ON (variant_id) variant_id, balance_after
    FROM stock_movements ORDER BY variant_id, id DESC
)
SELECT pv.id, pv.barcode, pv.stock, coalesce(agg.total, 0), coalesce(last.balance_after, 0)
  FROM product_variants pv
  LEFT JOIN agg  ON agg.variant_id  = pv.id
  LEFT JOIN last ON last.variant_id = pv.id
 WHERE pv.stock <> coalesce(agg.total, 0)
    OR pv.stock <> coalesce(last.balance_after, 0)
 ORDER BY pv.id
"""

# Saldo berjalan per varian: balance_after[i] = balance_after[i-1] + qty[i] (urut id).
RUNNING_BALANCE_SQL = """
SELECT id, variant_id, qty, balance_after, prev_balance
  FROM (
    SELECT id, variant_id, qty, balance_after,
           coalesce(lag(balance_after) OVER w, 0) AS prev_balance,
           lag(created_at) OVER w AS prev_created_at,
           created_at
      FROM stock_movements
    WINDOW w AS (PARTITION BY variant_id ORDER BY id)
  ) t
 WHERE balance_after <> prev_balance + qty
    OR (prev_created_at IS NOT NULL AND created_at < prev_created_at)
 ORDER BY id
"""


@dataclass(frozen=True)
class StockIssue:
    kind: str
    detail: tuple[object, ...]


def libpq_url(sqlalchemy_url: str) -> str:
    """postgresql+psycopg://... -> postgresql://... (untuk psycopg langsung)."""
    scheme, sep, rest = sqlalchemy_url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


def find_stock_issues(conn: psycopg.Connection) -> list[StockIssue]:
    issues: list[StockIssue] = []
    with conn.cursor() as cur:
        cur.execute(STOCK_MISMATCH_SQL)
        issues += [StockIssue("cache_mismatch", tuple(r)) for r in cur.fetchall()]
        cur.execute(RUNNING_BALANCE_SQL)
        issues += [StockIssue("running_balance", tuple(r)) for r in cur.fetchall()]
    return issues
