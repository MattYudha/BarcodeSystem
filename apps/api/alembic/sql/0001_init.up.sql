-- =============================================================================
-- Bhavia Inventory — schema awal
--
-- Prinsip:
--   * Stok HANYA berubah lewat INSERT ke stock_movements. Trigger mengunci baris
--     varian (FOR UPDATE), menghitung saldo, menolak stok negatif, mengisi
--     balance_after, lalu memperbarui cache product_variants.stock.
--   * Transaksi & audit log immutable (UPDATE/DELETE/TRUNCATE ditolak).
--   * Barcode & kode produk dibuat sistem dan tidak bisa diubah.
--   * Error bisnis dikirim sebagai SQLSTATE P0001 dengan MESSAGE = kode error
--     (mis. INSUFFICIENT_STOCK) dan DETAIL = JSON, dipetakan API ke pesan Indonesia.
--   * Semua waktu TIMESTAMPTZ (UTC); tampilan WIB diurus aplikasi.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TYPE user_role       AS ENUM ('admin', 'staff');
CREATE TYPE movement_type   AS ENUM ('IN', 'OUT', 'ADJUST', 'REVERSAL');
CREATE TYPE out_reason      AS ENUM ('sale', 'return_to_production', 'damaged', 'other');
CREATE TYPE movement_source AS ENUM ('scanner', 'camera', 'manual', 'initial', 'opname');
CREATE TYPE opname_status   AS ENUM ('draft', 'finalized', 'cancelled');

-- -----------------------------------------------------------------------------
-- Helper
-- -----------------------------------------------------------------------------

-- Zero-pad TANPA memotong: lpad('12345', 4, '0') = '1234' (bug), fungsi ini -> '12345'.
CREATE FUNCTION bhv_format_seq(n BIGINT, width INT) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT CASE WHEN length(n::text) >= width THEN n::text ELSE lpad(n::text, width, '0') END
$$;

CREATE FUNCTION bhv_raise(code TEXT, detail JSONB DEFAULT '{}'::jsonb) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = code, DETAIL = detail::text;
END $$;

CREATE FUNCTION bhv_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

CREATE FUNCTION bhv_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM bhv_raise('IMMUTABLE_RECORD', jsonb_build_object('table', TG_TABLE_NAME, 'op', TG_OP));
  RETURN NULL;
END $$;

-- -----------------------------------------------------------------------------
-- Akun, sesi, percobaan login
-- -----------------------------------------------------------------------------

CREATE TABLE users (
  id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name                 VARCHAR(100) NOT NULL CHECK (btrim(name) <> ''),
  email                CITEXT NOT NULL UNIQUE
                         CHECK (char_length(email) <= 150 AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  password_hash        TEXT NOT NULL,
  role                 user_role NOT NULL DEFAULT 'staff',
  is_active            BOOLEAN NOT NULL DEFAULT TRUE,
  must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
  last_login_at        TIMESTAMPTZ,
  password_changed_at  TIMESTAMPTZ,
  created_by           BIGINT REFERENCES users(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_users_touch BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION bhv_touch_updated_at();

CREATE TABLE sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash   BYTEA NOT NULL UNIQUE,              -- sha256(token); token mentah hanya di cookie
  user_id      BIGINT NOT NULL REFERENCES users(id),
  device_id    UUID,                               -- dibuat sekali per browser (localStorage)
  device_label VARCHAR(60),                        -- mis. "HP Gudang 1"
  user_agent   TEXT,
  ip           INET,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,               -- batas absolut
  revoked_at   TIMESTAMPTZ,
  CHECK (expires_at > created_at)
);
CREATE INDEX idx_sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE login_attempts (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email      CITEXT NOT NULL,
  ip         INET,
  success    BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_login_attempts_email ON login_attempts (email, created_at);
CREATE INDEX idx_login_attempts_ip    ON login_attempts (ip, created_at);

-- -----------------------------------------------------------------------------
-- Katalog
-- -----------------------------------------------------------------------------

CREATE TABLE categories (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        CITEXT NOT NULL UNIQUE CHECK (btrim(name) <> '' AND char_length(name) <= 60),
  archived_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE product_code_seq AS BIGINT;

CREATE TABLE products (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id     BIGINT NOT NULL REFERENCES categories(id),
  code            VARCHAR(20) NOT NULL UNIQUE           -- BHV-0001, diisi trigger insert
                    CHECK (code ~ '^BHV-[0-9]{4,}$'),
  name            VARCHAR(150) NOT NULL CHECK (btrim(name) <> ''),
  description     TEXT,
  price           NUMERIC(14, 2) CHECK (price IS NULL OR price >= 0),
  next_variant_no INT NOT NULL DEFAULT 1 CHECK (next_variant_no >= 1),
  archived_at     TIMESTAMPTZ,
  created_by      BIGINT REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER SEQUENCE product_code_seq OWNED BY products.code;
CREATE INDEX idx_products_category  ON products (category_id);
CREATE INDEX idx_products_name_trgm ON products USING gin (name gin_trgm_ops);

-- Kode produk selalu dari sequence (nilai kiriman client diabaikan).
CREATE FUNCTION bhv_products_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.code            := 'BHV-' || bhv_format_seq(nextval('product_code_seq'), 4);
  NEW.next_variant_no := 1;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_products_before_insert BEFORE INSERT ON products
  FOR EACH ROW EXECUTE FUNCTION bhv_products_before_insert();

CREATE FUNCTION bhv_products_before_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    PERFORM bhv_raise('IMMUTABLE_FIELD', jsonb_build_object('field', 'products.code'));
  END IF;
  IF NEW.next_variant_no < OLD.next_variant_no THEN
    PERFORM bhv_raise('IMMUTABLE_FIELD', jsonb_build_object('field', 'products.next_variant_no'));
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER trg_products_before_update BEFORE UPDATE ON products
  FOR EACH ROW EXECUTE FUNCTION bhv_products_before_update();

CREATE TABLE product_variants (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id  BIGINT NOT NULL REFERENCES products(id),
  variant_no  INT NOT NULL CHECK (variant_no >= 1),
  barcode     VARCHAR(40) NOT NULL UNIQUE CHECK (barcode ~ '^BHV-[0-9]{4,}-[0-9]{2,}$'),
  -- Normalisasi dipaksa DB: ukuran UPPERCASE tanpa spasi tepi; warna NULL atau teks ter-trim.
  size        VARCHAR(20) NOT NULL CHECK (btrim(size) <> '' AND size = upper(btrim(size))),
  color       VARCHAR(40) CHECK (color IS NULL OR (btrim(color) <> '' AND color = btrim(color))),
  min_stock   INT NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
  stock       INT NOT NULL DEFAULT 0 CHECK (stock >= 0),   -- cache; hanya diubah trigger movement
  archived_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (product_id, variant_no)
);
-- Kombinasi ukuran+warna unik per produk; warna NULL dianggap sama & case-insensitive.
CREATE UNIQUE INDEX uq_variants_product_size_color
  ON product_variants (product_id, size, lower(coalesce(color, '')));
CREATE INDEX idx_variants_product ON product_variants (product_id);
CREATE INDEX idx_variants_low_stock ON product_variants (id)
  WHERE archived_at IS NULL AND min_stock > 0 AND stock <= min_stock;

CREATE FUNCTION bhv_variants_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  p_code     TEXT;
  p_next     INT;
  p_archived TIMESTAMPTZ;
BEGIN
  -- Kunci produk agar nomor varian tidak bentrok saat insert paralel.
  SELECT code, next_variant_no, archived_at INTO p_code, p_next, p_archived
    FROM products WHERE id = NEW.product_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM bhv_raise('PRODUCT_NOT_FOUND', jsonb_build_object('product_id', NEW.product_id));
  END IF;
  IF p_archived IS NOT NULL THEN
    PERFORM bhv_raise('PRODUCT_ARCHIVED', jsonb_build_object('product_id', NEW.product_id));
  END IF;

  NEW.variant_no := p_next;
  NEW.barcode    := p_code || '-' || bhv_format_seq(p_next, 2);   -- abaikan nilai kiriman
  NEW.stock      := 0;                                              -- stok awal wajib via IN
  NEW.created_at := now();
  NEW.updated_at := now();

  UPDATE products SET next_variant_no = p_next + 1 WHERE id = NEW.product_id;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_variants_before_insert BEFORE INSERT ON product_variants
  FOR EACH ROW EXECUTE FUNCTION bhv_variants_before_insert();

CREATE FUNCTION bhv_variants_before_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.barcode    IS DISTINCT FROM OLD.barcode
  OR NEW.product_id IS DISTINCT FROM OLD.product_id
  OR NEW.variant_no IS DISTINCT FROM OLD.variant_no THEN
    PERFORM bhv_raise('IMMUTABLE_FIELD',
      jsonb_build_object('field', 'product_variants.barcode/product_id/variant_no'));
  END IF;
  IF NEW.stock IS DISTINCT FROM OLD.stock
     AND coalesce(current_setting('bhv.stock_write', true), '') <> 'on' THEN
    PERFORM bhv_raise('STOCK_DIRECT_WRITE', jsonb_build_object('variant_id', OLD.id));
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER trg_variants_before_update BEFORE UPDATE ON product_variants
  FOR EACH ROW EXECUTE FUNCTION bhv_variants_before_update();

-- -----------------------------------------------------------------------------
-- Stock opname
-- -----------------------------------------------------------------------------

CREATE SEQUENCE stock_opname_code_seq AS BIGINT;

CREATE TABLE stock_opnames (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code         VARCHAR(20) NOT NULL UNIQUE
                 DEFAULT ('SO-' || bhv_format_seq(nextval('stock_opname_code_seq'), 4)),
  status       opname_status NOT NULL DEFAULT 'draft',
  note         TEXT,
  created_by   BIGINT NOT NULL REFERENCES users(id),
  finalized_by BIGINT REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finalized_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((status = 'finalized') = (finalized_at IS NOT NULL AND finalized_by IS NOT NULL)),
  CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);
ALTER SEQUENCE stock_opname_code_seq OWNED BY stock_opnames.code;
-- Hanya boleh ada satu opname draft pada satu waktu.
CREATE UNIQUE INDEX uq_stock_opnames_single_draft ON stock_opnames ((true)) WHERE status = 'draft';

CREATE FUNCTION bhv_opnames_before_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' THEN
    PERFORM bhv_raise('OPNAME_CLOSED', jsonb_build_object('opname_id', OLD.id, 'status', OLD.status));
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER trg_opnames_before_update BEFORE UPDATE ON stock_opnames
  FOR EACH ROW EXECUTE FUNCTION bhv_opnames_before_update();
CREATE TRIGGER trg_opnames_no_delete BEFORE DELETE ON stock_opnames
  FOR EACH ROW EXECUTE FUNCTION bhv_reject_mutation();

CREATE TABLE stock_opname_items (
  opname_id   BIGINT NOT NULL REFERENCES stock_opnames(id),
  variant_id  BIGINT NOT NULL REFERENCES product_variants(id),
  counted_qty INT NOT NULL CHECK (counted_qty >= 0),
  system_qty  INT CHECK (system_qty >= 0),          -- diisi saat finalize (stok saat itu)
  diff        INT,                                  -- counted_qty - system_qty
  counted_by  BIGINT NOT NULL REFERENCES users(id),
  counted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (opname_id, variant_id),
  CHECK ((system_qty IS NULL) = (diff IS NULL)),
  CHECK (diff IS NULL OR diff = counted_qty - system_qty)
);
CREATE INDEX idx_opname_items_variant ON stock_opname_items (variant_id);

CREATE FUNCTION bhv_opname_items_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  o_id     BIGINT;
  v_status opname_status;
BEGIN
  IF TG_OP = 'DELETE' THEN o_id := OLD.opname_id; ELSE o_id := NEW.opname_id; END IF;
  SELECT so.status INTO v_status FROM stock_opnames so WHERE so.id = o_id;
  IF v_status IS DISTINCT FROM 'draft' THEN
    PERFORM bhv_raise('OPNAME_CLOSED', jsonb_build_object('opname_id', o_id, 'status', v_status));
  END IF;
  RETURN coalesce(NEW, OLD);
END $$;
CREATE TRIGGER trg_opname_items_guard BEFORE INSERT OR UPDATE OR DELETE ON stock_opname_items
  FOR EACH ROW EXECUTE FUNCTION bhv_opname_items_guard();

-- -----------------------------------------------------------------------------
-- Pergerakan stok
-- -----------------------------------------------------------------------------

-- Satu submit dari client (keranjang scan / opname / penyesuaian / pembatalan).
-- id = Idempotency-Key dari client -> submit ulang tidak membuat transaksi ganda.
CREATE TABLE movement_groups (
  id           UUID PRIMARY KEY,
  kind         movement_type NOT NULL,
  request_hash TEXT NOT NULL,                       -- key sama + payload beda -> ditolak API
  line_count   INT NOT NULL CHECK (line_count > 0),
  user_id      BIGINT NOT NULL REFERENCES users(id),
  session_id   UUID REFERENCES sessions(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_movement_groups_user ON movement_groups (user_id, created_at);

CREATE TABLE stock_movements (
  id              BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  group_id        UUID REFERENCES movement_groups(id),
  variant_id      BIGINT NOT NULL REFERENCES product_variants(id),
  type            movement_type NOT NULL,
  qty             INT NOT NULL CHECK (qty <> 0),      -- IN > 0, OUT < 0, ADJUST/REVERSAL +/-
  balance_after   INT NOT NULL CHECK (balance_after >= 0),  -- diisi trigger
  reason          out_reason,
  production_date DATE,
  batch_code      VARCHAR(40),
  note            TEXT CHECK (note IS NULL OR char_length(note) <= 500),
  reversal_of     BIGINT UNIQUE REFERENCES stock_movements(id),   -- sekali batal saja
  opname_id       BIGINT REFERENCES stock_opnames(id),
  source          movement_source NOT NULL,
  user_id         BIGINT NOT NULL REFERENCES users(id),
  session_id      UUID REFERENCES sessions(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),          -- di-set trigger (clock_timestamp)

  CONSTRAINT ck_mv_in_positive     CHECK (type <> 'IN'  OR qty > 0),
  CONSTRAINT ck_mv_out_negative    CHECK (type <> 'OUT' OR qty < 0),
  CONSTRAINT ck_mv_reason_only_out CHECK ((type = 'OUT') = (reason IS NOT NULL)),
  CONSTRAINT ck_mv_other_needs_note
    CHECK (reason IS DISTINCT FROM 'other' OR btrim(coalesce(note, '')) <> ''),
  CONSTRAINT ck_mv_production_only_in
    CHECK (type = 'IN' OR (production_date IS NULL AND batch_code IS NULL)),
  CONSTRAINT ck_mv_adjust_needs_note
    CHECK (type <> 'ADJUST' OR btrim(coalesce(note, '')) <> ''),
  CONSTRAINT ck_mv_reversal_needs_note
    CHECK (type <> 'REVERSAL' OR btrim(coalesce(note, '')) <> ''),
  CONSTRAINT ck_mv_reversal_link   CHECK ((type = 'REVERSAL') = (reversal_of IS NOT NULL)),
  CONSTRAINT ck_mv_opname_link
    CHECK ((source = 'opname') = (opname_id IS NOT NULL) AND (opname_id IS NULL OR type = 'ADJUST')),
  CONSTRAINT ck_mv_initial_is_in   CHECK (source <> 'initial' OR type = 'IN')
);
CREATE INDEX idx_movements_variant_id   ON stock_movements (variant_id, id);
CREATE INDEX idx_movements_variant_time ON stock_movements (variant_id, created_at);
CREATE INDEX idx_movements_time         ON stock_movements (created_at);
CREATE INDEX idx_movements_type_time    ON stock_movements (type, created_at);
CREATE INDEX idx_movements_user_time    ON stock_movements (user_id, created_at);
CREATE INDEX idx_movements_group        ON stock_movements (group_id);

CREATE FUNCTION bhv_apply_stock_movement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_stock     INT;
  v_archived  TIMESTAMPTZ;
  p_archived  TIMESTAMPTZ;
  o           RECORD;
  new_balance BIGINT;
BEGIN
  -- 1) Kunci baris varian: semua mutasi stok untuk varian ini menjadi serial.
  SELECT pv.stock, pv.archived_at, p.archived_at
    INTO v_stock, v_archived, p_archived
    FROM product_variants pv
    JOIN products p ON p.id = pv.product_id
   WHERE pv.id = NEW.variant_id
     FOR UPDATE OF pv;
  IF NOT FOUND THEN
    PERFORM bhv_raise('VARIANT_NOT_FOUND', jsonb_build_object('variant_id', NEW.variant_id));
  END IF;

  -- 2) Barang arsip tidak boleh scan masuk/keluar.
  IF NEW.type IN ('IN', 'OUT') AND (v_archived IS NOT NULL OR p_archived IS NOT NULL) THEN
    PERFORM bhv_raise('VARIANT_ARCHIVED', jsonb_build_object('variant_id', NEW.variant_id));
  END IF;

  -- 3) Validasi pembatalan (reversal_of NULL ditolak oleh CHECK ck_mv_reversal_link).
  IF NEW.type = 'REVERSAL' AND NEW.reversal_of IS NOT NULL THEN
    SELECT id, variant_id, type, qty INTO o FROM stock_movements WHERE id = NEW.reversal_of;
    IF NOT FOUND THEN
      PERFORM bhv_raise('MOVEMENT_NOT_FOUND', jsonb_build_object('movement_id', NEW.reversal_of));
    END IF;
    IF o.type = 'REVERSAL' THEN
      PERFORM bhv_raise('CANNOT_REVERSE_REVERSAL', jsonb_build_object('movement_id', o.id));
    END IF;
    IF o.variant_id <> NEW.variant_id OR NEW.qty <> -o.qty THEN
      PERFORM bhv_raise('REVERSAL_MISMATCH', jsonb_build_object('movement_id', o.id));
    END IF;
    IF EXISTS (SELECT 1 FROM stock_movements WHERE reversal_of = o.id) THEN
      PERFORM bhv_raise('ALREADY_REVERSED', jsonb_build_object('movement_id', o.id));
    END IF;
  END IF;

  -- 4) Saldo baru; stok tidak boleh negatif.
  new_balance := v_stock::BIGINT + NEW.qty;
  IF new_balance < 0 THEN
    PERFORM bhv_raise('INSUFFICIENT_STOCK', jsonb_build_object(
      'variant_id', NEW.variant_id, 'available', v_stock, 'requested', -NEW.qty));
  END IF;
  IF new_balance > 2147483647 THEN
    PERFORM bhv_raise('STOCK_OVERFLOW', jsonb_build_object('variant_id', NEW.variant_id));
  END IF;

  -- 5) id & waktu diambil SETELAH lock -> urutan id/created_at per varian = urutan saldo.
  --    Nilai id/created_at/balance_after dari client selalu diabaikan.
  NEW.id            := nextval(pg_get_serial_sequence('stock_movements', 'id'));
  NEW.created_at    := clock_timestamp();
  NEW.balance_after := new_balance;

  PERFORM set_config('bhv.stock_write', 'on', true);
  UPDATE product_variants SET stock = new_balance WHERE id = NEW.variant_id;
  PERFORM set_config('bhv.stock_write', 'off', true);

  RETURN NEW;
END $$;
CREATE TRIGGER trg_movements_apply BEFORE INSERT ON stock_movements
  FOR EACH ROW EXECUTE FUNCTION bhv_apply_stock_movement();
CREATE TRIGGER trg_movements_immutable BEFORE UPDATE OR DELETE ON stock_movements
  FOR EACH ROW EXECUTE FUNCTION bhv_reject_mutation();
CREATE TRIGGER trg_movements_no_truncate BEFORE TRUNCATE ON stock_movements
  FOR EACH STATEMENT EXECUTE FUNCTION bhv_reject_mutation();
CREATE TRIGGER trg_movement_groups_immutable BEFORE UPDATE OR DELETE ON movement_groups
  FOR EACH ROW EXECUTE FUNCTION bhv_reject_mutation();

-- -----------------------------------------------------------------------------
-- Audit log (perubahan master data, akun, cetak label, login)
-- -----------------------------------------------------------------------------

CREATE TABLE audit_logs (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id    BIGINT REFERENCES users(id),
  session_id  UUID REFERENCES sessions(id),
  action      VARCHAR(50) NOT NULL,            -- mis. user.create, product.archive, label.print
  entity_type VARCHAR(30),
  entity_id   BIGINT,
  before      JSONB,
  after       JSONB,
  ip          INET,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs (entity_type, entity_id, created_at);
CREATE INDEX idx_audit_time   ON audit_logs (created_at);
CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION bhv_reject_mutation();
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_logs
  FOR EACH STATEMENT EXECUTE FUNCTION bhv_reject_mutation();

-- -----------------------------------------------------------------------------
-- View stok per varian
-- -----------------------------------------------------------------------------

CREATE VIEW v_variant_stock AS
SELECT
  pv.id            AS variant_id,
  pv.barcode,
  pv.size,
  pv.color,
  pv.min_stock,
  pv.stock,
  p.id             AS product_id,
  p.code           AS product_code,
  p.name           AS product_name,
  p.price,
  c.id             AS category_id,
  c.name::text     AS category_name,
  (pv.archived_at IS NOT NULL OR p.archived_at IS NOT NULL) AS is_archived,
  CASE
    WHEN pv.stock = 0              THEN 'out'
    WHEN pv.stock <= pv.min_stock  THEN 'low'
    ELSE 'ok'
  END              AS stock_status,
  (pv.min_stock > 0 AND pv.stock <= pv.min_stock) AS is_alert
FROM product_variants pv
JOIN products   p ON p.id = pv.product_id
JOIN categories c ON c.id = p.category_id;
