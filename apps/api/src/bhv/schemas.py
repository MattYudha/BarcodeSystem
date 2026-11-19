"""Skema request/response API (Pydantic v2).

Normalisasi input dilakukan di sini; DB tetap memvalidasi ulang."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    model_validator,
)

from bhv.timeutil import today_wib

Role = Literal["admin", "staff"]
StockStatus = Literal["ok", "low", "out"]
ArchivedFilter = Literal["active", "archived", "all"]


def _squash(v: object) -> object:
    """Trim + rapatkan spasi ganda."""
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v


def _empty_to_none(v: object) -> object:
    v = _squash(v)
    return None if v == "" else v


def _upper(v: object) -> object:
    v = _squash(v)
    return v.upper() if isinstance(v, str) else v


def _lower(v: object) -> object:
    return v.strip().lower() if isinstance(v, str) else v


# Teks opsional: "" / spasi -> None; batas panjang HANYA untuk cabang string.
# Jangan tulis `Annotated[str | None, Field(max_length=n)]`: Pydantic menerapkan max_length ke
# seluruh union sehingga nilai null -> TypeError -> HTTP 500 (bug yang ditangkap E2E web).
_Str40 = Annotated[str, Field(max_length=40)]
_Str60 = Annotated[str, Field(max_length=60)]
_Str500 = Annotated[str, Field(max_length=500)]
_Str2000 = Annotated[str, Field(max_length=2000)]

Name = Annotated[str, BeforeValidator(_squash), Field(min_length=1, max_length=150)]
ShortName = Annotated[str, BeforeValidator(_squash), Field(min_length=1, max_length=100)]
CategoryName = Annotated[str, BeforeValidator(_squash), Field(min_length=1, max_length=60)]
Email = Annotated[EmailStr, BeforeValidator(_lower), Field(max_length=150)]
Size = Annotated[str, BeforeValidator(_upper), Field(min_length=1, max_length=20)]
Color = Annotated[_Str40 | None, BeforeValidator(_empty_to_none)]
OptText = Annotated[_Str2000 | None, BeforeValidator(_empty_to_none)]
BatchCode = Annotated[_Str40 | None, BeforeValidator(_empty_to_none)]
NoteText = Annotated[_Str500 | None, BeforeValidator(_empty_to_none)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Qty = Annotated[int, Field(ge=0, le=1_000_000)]
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]


def _not_future(d: date | None) -> date | None:
    if d is not None and d > today_wib():
        raise ValueError("Tanggal produksi tidak boleh di masa depan")
    return d


ProductionDate = Annotated[date | None, AfterValidator(_not_future)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------- auth & akun


LoginEmail = Annotated[str, BeforeValidator(_lower), Field(min_length=3, max_length=150)]


class LoginIn(Model):
    email: LoginEmail  # tanpa validasi format ketat: cukup dicocokkan ke DB
    password: Annotated[str, Field(min_length=1, max_length=128)]
    device_label: Annotated[_Str60 | None, BeforeValidator(_empty_to_none)] = None


class MeOut(BaseModel):
    id: int
    name: str
    email: str
    role: Role
    must_change_password: bool


class ChangePasswordIn(Model):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: Role
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreateIn(Model):
    name: ShortName
    email: Email
    role: Role = "staff"
    password: Password | None = None  # kosong -> password sementara dibuat sistem


class UserCreatedOut(UserOut):
    temp_password: str | None = None


class UserPatchIn(Model):
    name: ShortName | None = None
    role: Role | None = None
    is_active: bool | None = None


class TempPasswordOut(BaseModel):
    temp_password: str


# ---------------------------------------------------------------------------- katalog


class CategoryIn(Model):
    name: CategoryName


class CategoryOut(BaseModel):
    id: int
    name: str
    archived_at: datetime | None
    product_count: int = 0


class VariantIn(Model):
    size: Size
    color: Color = None
    min_stock: Qty = 0
    initial_stock: Qty = 0
    production_date: ProductionDate = None
    batch_code: BatchCode = None

    @model_validator(mode="after")
    def _batch_needs_stock(self) -> "VariantIn":
        if self.initial_stock == 0 and (self.production_date or self.batch_code):
            raise ValueError("Tanggal produksi/batch hanya diisi jika ada stok awal")
        return self


def _unique_variants(vs: list[VariantIn]) -> list[VariantIn]:
    seen: set[tuple[str, str]] = set()
    for v in vs:
        key = (v.size, (v.color or "").lower())
        if key in seen:
            raise ValueError(f"Varian ganda: ukuran {v.size} warna {v.color or '-'}")
        seen.add(key)
    return vs


class ProductCreateIn(Model):
    category_id: int
    name: Name
    description: OptText = None
    price: Money | None = None
    variants: Annotated[
        list[VariantIn], Field(min_length=1, max_length=100), AfterValidator(_unique_variants)
    ]


class ProductPatchIn(Model):
    category_id: int | None = None
    name: Name | None = None
    description: OptText = None
    price: Money | None = None


class VariantPatchIn(Model):
    size: Size | None = None
    color: Color = None
    min_stock: Qty | None = None


class VariantOut(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    category_id: int
    category_name: str
    price: Money | None
    barcode: str
    size: str
    color: str | None
    min_stock: int
    stock: int
    stock_status: StockStatus
    is_alert: bool
    is_archived: bool
    has_movements: bool = False  # True -> ukuran/warna tidak bisa diubah


class CategoryRef(BaseModel):
    id: int
    name: str


class ProductOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    price: Money | None
    category: CategoryRef
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    variant_count: int
    total_stock: int
    alert_count: int
    has_movements: bool
    variants: list[VariantOut]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------- label

LabelTemplateKey = Literal["a4_3x8", "a4_4x10", "thermal_50x30", "thermal_40x30"]


class LabelItemIn(Model):
    variant_id: int
    copies: Annotated[int, Field(ge=1, le=500)] = 1


class LabelRequestIn(Model):
    template: LabelTemplateKey = "a4_3x8"
    items: Annotated[list[LabelItemIn], Field(min_length=1, max_length=500)]
    show_price: bool = False
    start_position: Annotated[int, Field(ge=1, le=40)] = 1  # lewati stiker A4 yang sudah terpakai
