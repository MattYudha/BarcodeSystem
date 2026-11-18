# Bhavia Inventory — Sistem Inventaris Barcode

Aplikasi web pencatatan stok pakaian Bhavia International Tailor lewat scan barcode (masuk/keluar gudang, stock opname, laporan). Rancangan lengkap: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Bagian | Teknologi | Lokasi | Deploy |
|---|---|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, python-barcode, reportlab | `apps/api` | Docker di VPS (CloudPanel reverse proxy) |
| Database | PostgreSQL 17 | `apps/api/alembic` | Container di VPS |
| Web | Next.js + TypeScript | `apps/web` *(menyusul)* | Vercel |

## Status
- [x] M0 Fondasi: monorepo, Docker via WSL, CI
- [x] M1 Database: schema, trigger stok, tes DB (67 tes)
- [ ] M2 API inti · M3 API stok · M4–M5 Web · M6 E2E · M7 Deploy

## Prasyarat (Windows, tanpa Docker Desktop)
- Docker Engine di WSL (`Ubuntu-22.04`), user masuk grup `docker`. Disarankan juga `sudo apt install docker-buildx` (build lebih cepat; tanpa itu tetap jalan).
- [uv](https://docs.astral.sh/uv/) (otomatis mengunduh Python 3.12), Node 22+ dan pnpm.

## Menjalankan lokal
```powershell
copy .env.example .env               # opsional; default sudah cocok untuk lokal

.\scripts\dc.ps1 up -d --wait db     # Postgres di localhost:5433 (5432 sering dipakai Postgres lokal)

cd apps\api
uv sync
uv run bhv migrate                   # migrasi DB
uv run fastapi dev src/bhv/main.py   # API di http://localhost:8000/docs
```
Dari Git Bash/Linux gunakan `scripts/dc.sh` dengan argumen yang sama.

Stack lengkap dari image (sama seperti CI):
```powershell
.\scripts\dc.ps1 --profile full up -d --build --wait
curl http://localhost:8000/readyz
```

## Test & kualitas
```powershell
cd apps\api
uv run pytest          # memakai DB bhv_test (di-drop & dibuat ulang otomatis)
uv run ruff check . ; uv run ruff format --check . ; uv run mypy
uv run bhv check-stock # rekonsiliasi: stok cache = Σ transaksi = saldo berjalan
```

## Aturan stok yang dijaga oleh database
- Stok hanya berubah lewat `stock_movements`; `UPDATE product_variants SET stock` langsung ditolak.
- Setiap transaksi mengunci baris varian → tidak ada stok minus walau scan bersamaan.
- Transaksi tidak bisa diubah/dihapus; koreksi lewat `REVERSAL` (sekali per transaksi, wajib catatan).
- Barcode `BHV-0001-01` dibuat sistem dan tidak bisa diubah.
