"""Format error seragam: {"code", "message", "details"} dengan pesan Bahasa Indonesia.

Error bisnis dari trigger DB (SQLSTATE P0001, MESSAGE = kode) dipetakan lewat CATALOG.
"""

import json
from typing import Any

import psycopg.errors as pg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

# kode -> (HTTP status, pesan)
CATALOG: dict[str, tuple[int, str]] = {
    # umum
    "VALIDATION_ERROR": (422, "Data yang dikirim tidak valid."),
    "NOT_FOUND": (404, "Data tidak ditemukan."),
    "CONFLICT": (409, "Data bentrok dengan data lain."),
    "INTERNAL_ERROR": (500, "Terjadi kesalahan pada server."),
    "CSRF_REJECTED": (403, "Permintaan ditolak (origin tidak diizinkan)."),
    # auth
    "UNAUTHENTICATED": (401, "Silakan login terlebih dahulu."),
    "SESSION_EXPIRED": (401, "Sesi berakhir karena tidak aktif. Silakan login kembali."),
    "INVALID_CREDENTIALS": (401, "Email atau password salah."),
    "ACCOUNT_INACTIVE": (403, "Akun dinonaktifkan. Hubungi admin."),
    "LOGIN_LOCKED": (429, "Terlalu banyak percobaan login. Coba lagi nanti."),
    "FORBIDDEN": (403, "Anda tidak punya akses untuk tindakan ini."),
    "PASSWORD_CHANGE_REQUIRED": (403, "Anda wajib mengganti password terlebih dahulu."),
    "WRONG_PASSWORD": (422, "Password saat ini salah."),
    "PASSWORD_REUSED": (422, "Password baru tidak boleh sama dengan password lama."),
    # akun
    "EMAIL_TAKEN": (409, "Email sudah dipakai akun lain."),
    "USER_NOT_FOUND": (404, "Akun tidak ditemukan."),
    "CANNOT_MODIFY_SELF": (409, "Anda tidak bisa mengubah peran/status akun sendiri."),
    "LAST_ADMIN": (409, "Harus ada minimal satu admin aktif."),
    # katalog
    "CATEGORY_NOT_FOUND": (404, "Kategori tidak ditemukan."),
    "CATEGORY_TAKEN": (409, "Nama kategori sudah ada."),
    "CATEGORY_ARCHIVED": (409, "Kategori sudah diarsipkan."),
    "PRODUCT_NOT_FOUND": (404, "Barang tidak ditemukan."),
    "PRODUCT_ARCHIVED": (409, "Barang sudah diarsipkan."),
    "PRODUCT_HAS_MOVEMENTS": (
        409,
        "Barang sudah punya transaksi sehingga tidak bisa dihapus. Gunakan Arsipkan.",
    ),
    "VARIANT_NOT_FOUND": (404, "Barcode / varian tidak dikenal."),
    "VARIANT_ARCHIVED": (409, "Varian ini sudah diarsipkan dan tidak bisa dipakai transaksi."),
    "VARIANT_DUPLICATE": (409, "Kombinasi ukuran dan warna sudah ada pada barang ini."),
    "VARIANT_HAS_MOVEMENTS": (
        409,
        "Ukuran/warna tidak bisa diubah: varian sudah punya transaksi (label lama jadi salah).",
    ),
    # stok (dari trigger)
    "INSUFFICIENT_STOCK": (409, "Stok tidak cukup."),
    "STOCK_OVERFLOW": (409, "Jumlah stok melebihi batas."),
    "MOVEMENT_NOT_FOUND": (404, "Transaksi tidak ditemukan."),
    "ALREADY_REVERSED": (409, "Transaksi ini sudah dibatalkan."),
    "CANNOT_REVERSE_REVERSAL": (409, "Transaksi pembatalan tidak bisa dibatalkan lagi."),
    "REVERSAL_MISMATCH": (409, "Data pembatalan tidak sesuai transaksi asal."),
    "IMMUTABLE_RECORD": (409, "Data ini tidak bisa diubah atau dihapus."),
    "IMMUTABLE_FIELD": (409, "Kolom ini tidak bisa diubah."),
    "STOCK_DIRECT_WRITE": (409, "Stok hanya bisa diubah lewat transaksi."),
    "OPNAME_CLOSED": (409, "Stock opname sudah ditutup."),
    # label
    # transaksi
    "IDEMPOTENCY_KEY_REQUIRED": (422, "Header Idempotency-Key (UUID) wajib diisi."),
    "IDEMPOTENCY_MISMATCH": (
        409,
        "Kunci transaksi ini sudah dipakai untuk data yang berbeda. Muat ulang halaman.",
    ),
    "REVERSAL_NOT_ALLOWED": (
        403,
        "Staf hanya bisa membatalkan transaksi masuk/keluar miliknya sendiri maksimal 15 menit.",
    ),
    # opname
    "OPNAME_NOT_FOUND": (404, "Stock opname tidak ditemukan."),
    "OPNAME_DRAFT_EXISTS": (409, "Masih ada stock opname yang belum selesai."),
    "OPNAME_EMPTY": (422, "Belum ada barang yang dihitung."),
    "OPNAME_ITEM_NOT_FOUND": (404, "Barang ini belum dihitung pada opname ini."),
    # laporan
    "PERIOD_INVALID": (422, "Periode laporan tidak valid."),
    "LABEL_LIMIT": (422, "Jumlah label terlalu banyak dalam satu cetak."),
    "LABEL_TOO_SMALL": (
        422,
        "Barcode tidak muat di ukuran label ini tanpa mengurangi keterbacaan. "
        "Pilih label yang lebih lebar atau kertas A4.",
    ),
}


class AppError(Exception):
    def __init__(
        self, code: str, details: dict[str, Any] | None = None, message: str | None = None
    ) -> None:
        status, default_message = CATALOG.get(code, CATALOG["INTERNAL_ERROR"])
        self.code = code
        self.status = status
        self.message = message or default_message
        self.details = details or {}
        self.headers: dict[str, str] = {}
        super().__init__(code)


# Constraint unik -> kode error yang ramah.
_UNIQUE_MAP = {
    "users_email_key": "EMAIL_TAKEN",
    "categories_name_key": "CATEGORY_TAKEN",
    "uq_variants_product_size_color": "VARIANT_DUPLICATE",
    "uq_stock_opnames_single_draft": "OPNAME_DRAFT_EXISTS",
    "stock_movements_reversal_of_key": "ALREADY_REVERSED",  # pembatalan paralel
}


def from_db_error(exc: DBAPIError) -> AppError | None:
    orig = exc.orig
    if isinstance(orig, pg.RaiseException):
        code = orig.diag.message_primary or "INTERNAL_ERROR"
        try:
            details = json.loads(orig.diag.message_detail or "{}")
        except ValueError:
            details = {}
        if code in CATALOG:
            return AppError(code, details)
        return None
    if isinstance(orig, pg.UniqueViolation):
        return AppError(_UNIQUE_MAP.get(orig.diag.constraint_name or "", "CONFLICT"))
    if isinstance(orig, pg.CheckViolation):
        return AppError("VALIDATION_ERROR", {"constraint": orig.diag.constraint_name})
    if isinstance(orig, pg.ForeignKeyViolation):
        return AppError("CONFLICT", {"constraint": orig.diag.constraint_name})
    return None


def _body(err: AppError) -> dict[str, Any]:
    return {"code": err.code, "message": err.message, "details": err.details}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        err = from_db_error(exc)
        if err is None:
            raise exc
        return JSONResponse(_body(err), status_code=err.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        err = AppError("VALIDATION_ERROR", {"errors": errors})
        return JSONResponse(_body(err), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "NOT_FOUND"}.get(exc.status_code, "INTERNAL_ERROR")
        message = str(exc.detail) if exc.status_code not in (404, 405) else CATALOG[code][1]
        return JSONResponse(
            {"code": code, "message": message, "details": {}}, status_code=exc.status_code
        )
