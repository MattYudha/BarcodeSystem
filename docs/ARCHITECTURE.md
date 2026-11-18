# Arsitektur & Rencana Implementasi — Sistem Inventaris Barcode Bhavia

## Context
Klien (Bhavia International Tailor, order dari Vivo Livo) butuh sistem inventaris gudang berbasis scan barcode: barang masuk/keluar tercatat lengkap, stok akurat, laporan bisa diunduh. Prototipe HTML dari Pak Boss hanya acuan konsep; PRD (17/11/2026) sudah mendefinisikan scope v1, aturan bisnis, dan 6 temuan prototipe. Tugas: menyempurnakan schema, memilih stack, dan menyiapkan fondasi Docker (tanpa Docker Desktop) + CI/CD (GitHub → VPS CloudPanel untuk API/DB, Vercel untuk frontend) + E2E, supaya tidak ada bug logika/gap.

Kondisi environment (sudah dicek):
- `C:\Users\US3R\BARCODESYTEM` kosong. **Perhatian:** `C:\Users\US3R` sendiri adalah repo git → proyek wajib `git init` sendiri agar tidak ikut ke repo home.
- Docker Engine 29 + Compose v5 sudah jalan di WSL `Ubuntu-22.04` (user `matt` grup docker). Tidak ada Docker Desktop → dipanggil lewat wrapper CLI.
- Tersedia: Python 3.11, uv 0.7, Node 24, pnpm. Belum ada: `gh`, `vercel` CLI.

Keputusan user: API di **VPS + CloudPanel (Docker)**; alur scan **mode keranjang + per-item**.

---

## 1. Stack
| Lapisan | Pilihan | Alasan |
|---|---|---|
| Backend | **Python 3.12 + FastAPI**, SQLAlchemy 2 (async, psycopg 3), Alembic, Pydantic v2, Typer (CLI), uv | Sesuai permintaan Python; OpenAPI otomatis → kontrak type-safe ke frontend |
| Barcode | **python-barcode** (Code 128 → SVG/PNG preview) + **reportlab** (PDF label vektor, Code 128 native, layout A4/thermal) | Barcode tajam di semua printer, ukuran mm presisi |
| Database | **PostgreSQL 17** | Trigger, enum, `NULLS NOT DISTINCT`, row lock, citext, pg_trgm |
| Auth | Session cookie httpOnly (tabel `sessions`), argon2id (`pwdlib[argon2]`) | Idle-timeout & revoke instan saat akun dinonaktifkan (JWT tidak bisa) |
| Frontend | **Next.js (App Router) + TypeScript**, Tailwind + shadcn/ui, TanStack Query/Table, react-hook-form + zod, Recharts, date-fns (locale `id`, TZ Asia/Jakarta), `openapi-typescript` + `openapi-fetch` | Deploy native di Vercel |
| Scan kamera | `barcode-detector` ponyfill (native BarcodeDetector, fallback zxing-wasm; jalan juga di iOS Safari) | Satu API, format dibatasi `code_128` |
| Test | pytest (+hypothesis) pada Postgres asli, Vitest, **Playwright** E2E | Trigger/enum tidak bisa dites di SQLite |
| Infra | Docker Compose (via WSL CLI), GitHub Actions, GHCR, Vercel Git integration, CloudPanel reverse proxy + Let's Encrypt | |

**Arsitektur request:** Browser → Vercel (Next.js) → rewrite `/api/:path*` → `https://api.<domain>` (CloudPanel nginx) → container FastAPI → Postgres (container, bind `127.0.0.1` saja). Karena lewat rewrite, cookie jadi first-party di domain Vercel (tanpa CORS/third-party cookie). CSRF: `SameSite=Lax` + cek header `Origin` pada request mutasi.

---

## 2. Schema final (perbaikan atas DDL PRD)

### Gap pada DDL PRD yang diperbaiki
1. `UNIQUE (product_id, size, color)` **bocor saat `color` NULL** (NULL dianggap beda) → `UNIQUE NULLS NOT DISTINCT` + normalisasi (size UPPER/trim, color trim) + unique index case-insensitive.
2. Pembatalan tidak bisa dimodelkan: membalik OUT (qty −5) butuh qty +5, melanggar `CHECK OUT qty<0` → tambah tipe **`REVERSAL`**, `reversal_of` **UNIQUE** (sekali batal saja), reversal tidak boleh dibalik lagi, qty wajib = −qty asli.
3. `reason` bisa terisi di IN/ADJUST; `production_date` bisa di OUT; ADJUST tanpa catatan lolos → CHECK lengkap.
4. Kolom `stock` bisa di-UPDATE langsung oleh kode mana pun → stok **hanya** diubah oleh trigger `stock_movements` (guard `set_config` lokal); UPDATE langsung ditolak DB.
5. Race condition OUT → kunci baris varian (`FOR UPDATE`) **di dalam trigger** BEFORE INSERT; tidak bergantung disiplin kode aplikasi.
6. Transaksi bisa di-UPDATE/DELETE → trigger immutability.
7. Barcode bisa diubah → trigger immutability untuk `barcode`, `product_id`, `variant_no`, `products.code`.
8. `lpad(n,4)` memotong angka >9999 (bug klasik) → format pakai CASE; suffix varian 2 digit, melebar otomatis >99.
9. F-17 "perangkat" tidak ada tempatnya → tabel `sessions` (device_id, device_label, UA, IP) + `stock_movements.session_id`.
10. Double-submit (scanner kirim Enter 2x / jaringan retry) → tabel `movement_groups` dengan idempotency key dari client.
11. Kartu stok & saldo awal laporan mahal dihitung → kolom **`balance_after`** per transaksi (diisi trigger).
12. Tidak ada login-rate-limit, audit perubahan master data, stock opname → tabel `login_attempts`, `audit_logs`, `stock_opnames` + `stock_opname_items`.

### DDL (ringkas; ditulis sebagai migrasi Alembic `0001_init` dengan raw SQL)
```sql
CREATE EXTENSION IF NOT EXISTS citext; CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TYPE user_role       AS ENUM ('admin','staff');
CREATE TYPE movement_type   AS ENUM ('IN','OUT','ADJUST','REVERSAL');
CREATE TYPE out_reason      AS ENUM ('sale','return_to_production','damaged','other');
CREATE TYPE movement_source AS ENUM ('scanner','camera','manual','initial','opname');
CREATE TYPE opname_status   AS ENUM ('draft','finalized','cancelled');

users(id BIGSERIAL PK, name VARCHAR(100) NOT NULL, email CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, role user_role NOT NULL DEFAULT 'staff',
  is_active BOOL NOT NULL DEFAULT TRUE, must_change_password BOOL NOT NULL DEFAULT FALSE,
  last_login_at, password_changed_at TIMESTAMPTZ, created_by BIGINT FK users,
  created_at, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())

sessions(id UUID PK DEFAULT gen_random_uuid(), token_hash BYTEA UNIQUE NOT NULL,  -- sha256 token
  user_id FK users, device_id UUID, device_label VARCHAR(60), user_agent TEXT, ip INET,
  created_at, last_seen_at, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ)
  -- idle 30 mnt (last_seen_at), absolut 12 jam; INDEX (user_id) WHERE revoked_at IS NULL

login_attempts(id, email CITEXT, ip INET, success BOOL, created_at)  -- INDEX (email,created_at),(ip,created_at)

categories(id, name CITEXT UNIQUE NOT NULL, archived_at, created_at)

CREATE SEQUENCE product_code_seq;
products(id, category_id FK, code VARCHAR(20) UNIQUE NOT NULL,      -- BHV-0001 (default dari sequence)
  name VARCHAR(150) NOT NULL, description TEXT,
  price NUMERIC(14,2) CHECK (price IS NULL OR price >= 0),
  next_variant_no SMALLINT NOT NULL DEFAULT 1,
  archived_at, created_by FK users, created_at, updated_at)
  -- INDEX gin (name gin_trgm_ops) untuk pencarian

product_variants(id, product_id FK, variant_no SMALLINT NOT NULL,
  barcode VARCHAR(40) UNIQUE NOT NULL CHECK (barcode ~ '^BHV-[0-9]{4,}-[0-9]{2,}$'),
  size VARCHAR(20) NOT NULL, color VARCHAR(40),
  min_stock INT NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
  stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),            -- cache, hanya via trigger
  archived_at, created_at, updated_at,
  UNIQUE (product_id, variant_no),
  UNIQUE NULLS NOT DISTINCT (product_id, size, color))
  -- trigger BEFORE INSERT: lock product, ambil next_variant_no, bentuk barcode = code||'-'||NN

movement_groups(id UUID PK,                 -- = Idempotency-Key dari client (1 submit keranjang)
  kind movement_type NOT NULL, user_id FK, session_id FK sessions, line_count INT, created_at)

stock_movements(id BIGSERIAL PK, group_id UUID FK movement_groups,
  variant_id FK product_variants, type movement_type NOT NULL,
  qty INT NOT NULL CHECK (qty <> 0), balance_after INT NOT NULL CHECK (balance_after >= 0),
  reason out_reason, production_date DATE, batch_code VARCHAR(40), note TEXT,
  reversal_of BIGINT UNIQUE FK stock_movements, opname_id BIGINT FK stock_opnames,
  source movement_source NOT NULL, user_id FK users NOT NULL, session_id UUID FK sessions,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (type <> 'IN'  OR qty > 0),
  CHECK (type <> 'OUT' OR qty < 0),
  CHECK ((type = 'OUT') = (reason IS NOT NULL)),
  CHECK (reason IS DISTINCT FROM 'other' OR btrim(coalesce(note,'')) <> ''),
  CHECK (type = 'IN' OR (production_date IS NULL AND batch_code IS NULL)),
  CHECK (type <> 'ADJUST' OR btrim(coalesce(note,'')) <> ''),
  CHECK ((type = 'REVERSAL') = (reversal_of IS NOT NULL)),
  CHECK (opname_id IS NULL OR type = 'ADJUST'))
  -- INDEX (variant_id, id), (created_at), (type, created_at), (user_id, created_at)

stock_opnames(id, code VARCHAR(20) UNIQUE, status opname_status NOT NULL DEFAULT 'draft', note,
  created_by, finalized_by FK users, created_at, finalized_at, cancelled_at)
  -- UNIQUE INDEX ((true)) WHERE status='draft'  → hanya 1 opname aktif
stock_opname_items(opname_id FK, variant_id FK, counted_qty INT NOT NULL CHECK (>=0),
  system_qty INT, diff INT, counted_by FK users, counted_at, PRIMARY KEY (opname_id, variant_id))

audit_logs(id, actor_id FK users, session_id, action VARCHAR(50), entity_type VARCHAR(30),
  entity_id BIGINT, before JSONB, after JSONB, ip INET, created_at)   -- immutable
```

### Trigger kunci (`apply_stock_movement`, BEFORE INSERT ON stock_movements)
1. `SELECT stock, archived_at FROM product_variants WHERE id = NEW.variant_id FOR UPDATE`.
2. Varian arsip + tipe IN/OUT → `RAISE 'VARIANT_ARCHIVED'`.
3. REVERSAL: lock baris asli; tolak jika asli bertipe REVERSAL, beda varian, atau `NEW.qty <> -orig.qty`.
4. `new_balance = stock + NEW.qty`; < 0 → `RAISE 'INSUFFICIENT_STOCK'` (DETAIL berisi stok tersedia) → API memetakan ke 409 dengan pesan Indonesia.
5. `NEW.balance_after := new_balance`; `set_config('bhv.stock_write','on',true)`; `UPDATE product_variants SET stock = new_balance`.

Plus: trigger tolak UPDATE/DELETE di `stock_movements` & `audit_logs`; trigger tolak perubahan `stock` tanpa guard; FK tanpa CASCADE → varian/produk bertransaksi tidak bisa dihapus (hanya arsip). Insert multi-baris (keranjang/opname) diurutkan `variant_id` untuk mencegah deadlock.

### Aturan turunan (didefinisikan agar tidak ambigu)
- **Status stok:** `Habis` jika stok = 0; `Menipis` jika 0 < stok ≤ min_stock; kartu dashboard "Stok menipis" = varian aktif dengan `min_stock > 0 AND stock <= min_stock` (termasuk habis).
- **Laporan periode** (batas hari dihitung WIB → dikonversi ke UTC, `[start, end)`; minggu = Senin–Minggu; bulan = kalender): kolom per varian `Saldo awal | Masuk | Keluar | Penyesuaian | Pembatalan | Saldo akhir`, invariant `awal + Σqty = akhir` (dites). Saldo awal = `balance_after` terakhir sebelum `start`.
- **Pembatalan:** Admin kapan saja; Staf hanya transaksi miliknya ≤ 15 menit. Membatalkan IN yang barangnya sudah keluar otomatis ditolak (stok negatif).
- **Stock opname:** hitung bisa via scan (tiap scan +1) atau ketik; saat finalize, selisih dihitung terhadap stok **saat finalize** (`diff = counted − stock`), ADJUST dibuat hanya jika diff ≠ 0, dalam satu transaksi DB.
- **Produk baru:** produk + varian + IN "Stok awal" (source `initial`) dalam satu transaksi DB (memperbaiki temuan #1). Hard delete hanya jika belum ada transaksi; selain itu Arsipkan.
- **Akun:** tidak bisa menonaktifkan/menurunkan diri sendiri atau admin aktif terakhir; nonaktif/reset password → semua session dicabut; reset → `must_change_password`.
- **Login:** ≥5 gagal/email/15 mnt atau ≥20/IP/15 mnt → 429 dengan sisa waktu.
- **CSV:** UTF-8 BOM, delimiter `;` (Excel locale Indonesia), tanggal `DD/MM/YYYY HH:mm` WIB, sel teks diawali `= + - @` di-escape (CSV injection), streaming untuk data besar.

---

## 3. API (FastAPI, prefix `/api/v1`, error `{code, message, details}`)
- **Auth:** `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password`
- **Users (admin):** `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password`
- **Katalog:** `/categories` CRUD+archive; `/products` (list: `q, category_id, size, stock_status, archived, page`), `POST /products` (dengan `variants[]` + `initial_stock`), `PATCH /products/{id}`, `POST /products/{id}/archive|unarchive`, `POST /products/{id}/variants`, `PATCH /variants/{id}` (size/color/min_stock saja)
- **Scan:** `GET /variants/lookup?barcode=` (404 `VARIANT_NOT_FOUND`, 409 `VARIANT_ARCHIVED`)
- **Movements:** `POST /movements` (header `Idempotency-Key`, `type IN|OUT`, `lines[]`), `POST /movements/adjust` (admin), `POST /movements/{id}/reverse`, `GET /movements`
- **Kartu stok:** `GET /variants/{id}/stock-card?from&to`
- **Opname (admin):** `POST /opnames`, `GET /opnames/{id}`, `PUT /opnames/{id}/items`, `POST /opnames/{id}/finalize|cancel`
- **Laporan/Dashboard:** `GET /dashboard`, `GET /reports/summary`, `GET /reports/movements`, `GET /reports/movements.csv`, `GET /reports/stock.csv`
- **Label:** `GET /variants/{id}/barcode.svg` (python-barcode), `POST /labels/pdf` `{template, items:[{variant_id, copies}]}` (reportlab). Template awal: A4 stiker grid (konfigurasi mm: kolom/baris/margin), thermal 50×30 mm & 40×30 mm. Isi: nama, ukuran, warna, barcode + teks, harga opsional. Setelah IN berhasil ada tombol "Cetak label (N)".
- **Ops:** `GET /healthz`, `GET /readyz`
- **CLI (Typer, `bhv`):** `create-admin`, `seed` (data prototipe: Kemeja/Blazer/Celana/Gamis via IN), `seed-perf` (5.000 varian, 500.000 transaksi), `check-stock` (rekonsiliasi `stock = Σqty = balance_after terakhir`), `purge-sessions`.

Hak akses dicek di server lewat dependency `require_role(...)` di setiap router; frontend hanya menyembunyikan menu.

## 4. Frontend (Next.js, Bahasa Indonesia, responsif ≥360 px)
Halaman: `/login`, `/` dashboard (kartu F-03, grafik 7 hari + 10 transaksi terbaru F-04, alert menipis), `/barang` (tabel + filter F-07), `/barang/[id]` (varian, kartu stok F-16, cetak label), `/scan`, `/opname`, `/laporan`, `/pengguna` (admin), `/akun`.
- **Halaman Scan:** toggle Masuk/Keluar besar; mode **Keranjang** (default; scan barcode sama = qty+1, edit qty, alasan/tanggal produksi/batch per baris atau set default) dan **Per-item**. Input: hook keyboard-wedge global (deteksi ketikan cepat + Enter, tetap jalan tanpa fokus input) + tombol kamera (pilih kamera belakang, torch, debounce 1,5 dtk kode sama). Feedback F-12: beep WebAudio + getar + flash hijau/merah. Barcode tidak dikenal → toast jelas, tidak masuk keranjang. Stok tersedia ditampilkan per baris OUT & divalidasi sebelum kirim (server tetap final).
- `device_id` dibuat sekali di localStorage + label perangkat opsional ("HP Gudang 1"), dikirim header → tersimpan di session.
- Format tanggal `DD/MM/YYYY`, semua waktu ditampilkan WIB. Cetak laporan via print CSS.
- Tipe API digenerate dari OpenAPI FastAPI (`pnpm gen:api`); CI gagal jika tipe basi.

## 5. Struktur repo (monorepo)
```
BARCODESYTEM/
  apps/api/   pyproject.toml, uv.lock, Dockerfile, alembic/, src/bhv/{main,config,db,errors,cli}.py,
              src/bhv/{models,schemas,routers,services}/ (movements, opname, reports, labels, barcodes, auth),
              tests/{unit,integration}
  apps/web/   Next.js app (src/app, src/lib/api, src/hooks/useScanner*, e2e/ Playwright)
  infra/      docker-compose.yml (dev: db; profile full: db+api+web), docker-compose.prod.yml (api, db, backup),
              deploy/ (CloudPanel reverse-proxy notes, restore guide)
  scripts/    dc.ps1 + dc.sh (wrapper: wsl -d Ubuntu-22.04 docker compose ...), dev.ps1
  .github/    workflows/ci.yml, deploy.yml, dependabot.yml
  docs/       PRD.md, ARCHITECTURE.md, ERD (mermaid)
  .env.example, README.md
```

## 6. Docker lokal tanpa Docker Desktop
- `scripts/dc.ps1 up` → `wsl -d Ubuntu-22.04 --cd <path> docker compose -f infra/docker-compose.yml ...`; port WSL2 diteruskan ke `localhost` Windows.
- **Mode dev (harian):** hanya Postgres di Docker; API (`uv run fastapi dev`) dan web (`pnpm dev`) native di Windows → hot reload cepat (bind-mount `/mnt/c` ke container lambat & watcher tidak jalan).
- **Mode full (`--profile full`):** build image api+web, sama persis dengan CI E2E.
- Tes kamera dari HP di lokal: `cloudflared tunnel --url http://localhost:3000` (HTTPS wajib untuk kamera).

## 7. CI/CD
- **ci.yml** (PR + push): `api` (uv sync, ruff, mypy, alembic upgrade di service postgres:17, pytest + coverage) · `web` (pnpm lint, tsc, vitest, build, cek tipe OpenAPI terbaru) · `e2e` (compose profile full, `bhv seed`, Playwright, upload report/trace) · build image api.
- **deploy.yml** (push `main` setelah CI hijau): build & push image ke GHCR (`:sha`, `:latest`) → SSH ke VPS → `docker compose pull` → one-shot `alembic upgrade head` → `up -d` → cek `/readyz`; gagal → rollback ke tag sebelumnya. Secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.
- **Frontend:** Vercel Git integration (root `apps/web`, preview per PR, prod di `main`), env `API_ORIGIN`.
- **VPS:** CloudPanel site "Reverse Proxy" `api.<domain>` → `127.0.0.1:8000` + Let's Encrypt; Postgres tidak diekspos publik; backup `postgres-backup-local` harian, simpan 14 hari (+ opsi rclone off-site); restore drill didokumentasikan.
- Langkah manual oleh user nanti: buat repo GitHub (install `gh` via winget atau web), hubungkan Vercel, siapkan VPS/CloudPanel & secrets.

## 8. Milestone eksekusi
1. **M0 Fondasi:** `git init` di BARCODESYTEM, struktur monorepo, `.env.example`, compose db + wrapper WSL, skeleton CI.
2. **M1 Database:** migrasi 0001 (schema + trigger + view `v_variant_stock`), tes DB (constraint, trigger, concurrency).
3. **M2 API inti:** auth/session/rate-limit, users, kategori/produk/varian, barcode SVG, label PDF, audit log.
4. **M3 API stok:** movements (keranjang + idempotensi), reversal, adjust, opname, kartu stok, dashboard, laporan + CSV, CLI.
5. **M4 Web dasar:** layout, login, guard peran, barang, label.
6. **M5 Web stok:** scan (wedge + kamera + keranjang), opname, laporan, dashboard, pengguna.
7. **M6 E2E & performa:** Playwright penuh, `seed-perf` + ukur p95 scan & laporan.
8. **M7 Deploy:** Dockerfile prod, compose prod + backup, deploy.yml, panduan CloudPanel & Vercel.

## 9. Verifikasi
**Backend (pytest, Postgres asli):**
- 20 request OUT paralel qty 1 pada stok 10 → tepat 10 sukses, stok 0, tidak pernah negatif.
- Hypothesis: urutan acak IN/OUT/ADJUST/REVERSAL → selalu `stock = Σqty = balance_after terakhir`.
- `UPDATE product_variants SET stock=…` langsung, UPDATE/DELETE movement, ubah barcode → ditolak DB.
- Reversal ganda / reversal atas reversal ditolak; idempotency key sama → satu grup saja.
- Batas hari WIB: transaksi 23:30 WIB (16:30 UTC) masuk hari yang benar; invariant saldo laporan.
- Setiap endpoint admin diakses staf → 403; akun nonaktif → session langsung invalid; lockout login.

**E2E Playwright (dipetakan ke F-xx):** login/logout/idle timeout (timeout pendek di env test) · admin buat/nonaktif/reset staf · tambah produk 3 varian + stok awal → barcode `BHV-0001-01..03`, transaksi "Stok awal" ada, ganti nama tidak mengubah barcode · unduh label PDF (content-type, jumlah halaman) · scan masuk via simulasi keyboard-wedge · scan via kamera dengan `--use-fake-device-for-media-stream` + video barcode y4m · keluar melebihi stok ditolak · barcode tak dikenal tanpa transaksi · varian arsip tidak bisa di-scan · keranjang double submit → satu transaksi · pembatalan · opname → ADJUST sesuai selisih · laporan harian/mingguan/bulanan + isi CSV · staf tidak bisa akses halaman/API admin.

**Manual akhir:** `scripts/dc.ps1 up --profile full` → seed → coba alur A–D di Chrome desktop + HP Android via tunnel HTTPS; `bhv check-stock` = 0 selisih; `seed-perf` lalu cek scan < 1 detik dan laporan bulanan responsif.
