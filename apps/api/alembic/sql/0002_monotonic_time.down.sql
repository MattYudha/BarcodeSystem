-- kembalikan versi 0001
CREATE OR REPLACE FUNCTION bhv_apply_stock_movement() RETURNS trigger
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
