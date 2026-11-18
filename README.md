# Bhavia Inventory — Sistem Inventaris Barcode

Aplikasi web pencatatan stok pakaian Bhavia International Tailor lewat scan barcode (masuk/keluar gudang, stock opname, laporan). Rancangan lengkap: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Bagian | Teknologi | Lokasi | Deploy |
|---|---|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, python-barcode, reportlab | `apps/api` | Docker di VPS (CloudPanel reverse proxy) |
| Database | PostgreSQL 17 | `apps/api/alembic` | Container di VPS |
| Web | Next.js + TypeScript | `apps/web` *(menyusul)* | Vercel |

## Status
- [x] M0 Fondasi: monorepo, Docker via WSL, CI
- [x] M1 Database: schema, trigger stok, tes DB
- [x] M2 API inti: login/sesi/rate-limit, akun, kategori/barang/varian, barcode SVG, label PDF, audit log
- [x] M3 API stok: scan masuk/keluar (keranjang + idempotensi), penyesuaian, pembatalan, stock opname,
      kartu stok, dashboard, laporan harian/mingguan/bulanan + CSV (batas hari WIB), `bhv seed`
- [ ] M4–M5 Web (+ Playwright) · M6 E2E penuh & performa · M7 Deploy

Total 178 tes: 69 DB, 81 E2E API (HTTP), 28 unit (termasuk decode barcode label pada resolusi printer).

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
uv run bhv create-admin              # admin pertama (interaktif)
uv run bhv seed                      # opsional: data contoh dari prototipe
uv run bhv serve --reload            # API di http://localhost:8000/api/v1/docs
```
Dari Git Bash/Linux gunakan `scripts/dc.sh` dengan argumen yang sama.

Stack lengkap dari image (sama seperti CI):
```powershell
.\scripts\dc.ps1 --profile full up -d --build --wait
curl http://localhost:8000/readyz
```

> `bhv serve` memakai SelectorEventLoop: psycopg async tidak jalan di ProactorEventLoop default Windows.

## Test & kualitas
```powershell
cd apps\api
uv run pytest          # DB + unit + E2E API (uvicorn dijalankan otomatis; DB bhv_test dibuat ulang)
uv run ruff check . ; uv run ruff format --check . ; uv run mypy
uv run bhv check-stock # rekonsiliasi: stok cache = Σ transaksi = saldo berjalan
```

### E2E API terhadap stack Docker (sama seperti job CI `e2e-stack`)
```bash
scripts/dc.sh --profile full up -d --build --wait
scripts/dc.sh exec -T api bhv create-admin --email e2e-admin@bhavia-e2e.com --name "E2E Admin" --password "E2e-Admin-Pass1"
cd apps/api
E2E_BASE_URL=http://localhost:8000 E2E_ADMIN_EMAIL=e2e-admin@bhavia-e2e.com \
E2E_ADMIN_PASSWORD=E2e-Admin-Pass1 E2E_DATABASE_URL=postgresql://bhv:bhv@localhost:5433/bhv \
uv run pytest tests/api
```

## Troubleshooting WSL
**`localhost:5433` timeout / API tidak siap** — WSL mematikan distro beberapa saat setelah sesi
`wsl.exe` terakhir ditutup, dan Docker di dalamnya ikut berhenti. Jalankan di terminal terpisah:
```powershell
.\scripts\wsl-keepalive.ps1
```
Jika distro hidup tapi port tetap tidak bisa diakses dari Windows (relay `wslrelay.exe` macet),
`wsl --shutdown` lalu `.\scripts\dc.ps1 up -d --wait db` (ini juga menghentikan container lain di WSL).

## Label barcode
| Template | Untuk | Catatan |
|---|---|---|
| `a4_3x8` | Kertas stiker A4, 24 label 70×36 mm | printer biasa |
| `a4_4x10` | Kertas stiker A4, 40 label 48,5×25,4 mm | printer biasa |
| `thermal_50x30` | Printer label thermal 203 dpi | paling umum |
| `thermal_40x30` | Printer label thermal 300 dpi | di 203 dpi barcode tidak muat dengan andal |

Batang thermal selalu kelipatan titik printer (min. 2 titik). Label yang tidak bisa dicetak dengan andal
ditolak (`LABEL_TOO_SMALL`), bukan dicetak diam-diam dalam kondisi sulit di-scan.

## Aturan stok yang dijaga oleh database
- Stok hanya berubah lewat `stock_movements`; `UPDATE product_variants SET stock` langsung ditolak.
- Setiap transaksi mengunci baris varian → tidak ada stok minus walau scan bersamaan.
- Transaksi tidak bisa diubah/dihapus; koreksi lewat `REVERSAL` (sekali per transaksi, wajib catatan).
- Barcode `BHV-0001-01` dibuat sistem dan tidak bisa diubah.
