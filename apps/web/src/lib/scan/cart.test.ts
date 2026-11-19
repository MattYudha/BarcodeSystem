import { describe, expect, it } from "vitest";

import type { Variant } from "@/lib/api/client";

import { cartIssues, emptyCart, reduce, toRequest, totalQty, type Action, type Cart, type Defaults } from "./cart";

let n = 0;
const key = () => `k${++n}`;
const defaults: Defaults = { reason: "sale", production_date: "2026-11-01", batch_code: "B1" };

function variant(id: number, stock = 10, size = "M"): Variant {
  return {
    id, product_id: 1, product_code: "BHV-0001", product_name: "Kemeja", category_id: 1,
    category_name: "Kemeja", price: null, barcode: `BHV-0001-0${id}`, size, color: null,
    min_stock: 0, stock, stock_status: "ok", is_alert: false, is_archived: false, has_movements: true,
  };
}

const run = (cart: Cart, ...actions: Action[]) => actions.reduce((c, a) => reduce(c, a, key), cart);
const scan = (v: Variant, source: "scanner" | "camera" = "scanner", single = false): Action =>
  ({ type: "scan", variant: v, source, single, defaults });

describe("keranjang scan", () => {
  it("scan barcode sama menambah jumlah, bukan baris baru", () => {
    const c = run(emptyCart("IN", key()), scan(variant(1)), scan(variant(2)), scan(variant(1)));
    expect(c.lines.map((l) => [l.variant.id, l.qty])).toEqual([[1, 2], [2, 1]]);
    expect(totalQty(c)).toBe(3);
  });

  it("mode per-item mengganti item yang sedang diproses", () => {
    const c = run(emptyCart("IN", key()), scan(variant(1), "scanner", true), scan(variant(2), "scanner", true));
    expect(c.lines.map((l) => l.variant.id)).toEqual([2]);
  });

  it("setiap perubahan membuat Idempotency-Key baru; tanpa perubahan kunci tetap", () => {
    const a = run(emptyCart("IN", key()), scan(variant(1)));
    const b = reduce(a, { type: "qty", variantId: 1, qty: 5 }, key);
    expect(b.key).not.toBe(a.key);
    expect(toRequest(a)).toEqual(toRequest(a)); // kirim ulang = payload & kunci sama
    const c = reduce(b, { type: "mode", mode: "OUT" }, key); // ditolak: keranjang berisi
    expect(c).toBe(b);
  });

  it("default tanggal produksi/batch hanya untuk masuk, alasan hanya untuk keluar", () => {
    const masuk = toRequest(run(emptyCart("IN", key()), scan(variant(1))));
    expect(masuk.lines[0]).toMatchObject({ reason: null, production_date: "2026-11-01", batch_code: "B1" });
    const keluar = toRequest(run(emptyCart("OUT", key()), scan(variant(1))));
    expect(keluar.lines[0]).toMatchObject({ reason: "sale", production_date: null, batch_code: null });
  });

  it("validasi keluar: melebihi stok, alasan lainnya tanpa catatan", () => {
    let c = run(emptyCart("OUT", key()), scan(variant(1, 1)), scan(variant(1, 1)));
    expect(cartIssues(c)).toEqual(["Kemeja (M): Melebihi stok (tersedia 1)"]);
    c = run(c, { type: "qty", variantId: 1, qty: 1 }, { type: "field", variantId: 1, patch: { reason: "other" } });
    expect(cartIssues(c)).toEqual(["Kemeja (M): Isi catatan untuk alasan lainnya"]);
    c = reduce(c, { type: "field", variantId: 1, patch: { note: "sampel" } }, key);
    expect(cartIssues(c)).toEqual([]);
  });

  it("jumlah selalu bilangan bulat 1..100000", () => {
    const c = run(emptyCart("IN", key()), scan(variant(1)));
    for (const [input, expected] of [[0, 1], [-5, 1], [2.7, 2], [Number.NaN, 1], [10_000_000, 100_000]]) {
      expect(reduce(c, { type: "qty", variantId: 1, qty: input }, key).lines[0].qty).toBe(expected);
    }
  });

  it("sumber kamera tercatat bila ada baris dari kamera", () => {
    const c = run(emptyCart("IN", key()), scan(variant(1)), scan(variant(2), "camera"), scan(variant(3)));
    expect(c.source).toBe("camera");
    expect(run(c, { type: "clear" }).source).toBe("scanner");
  });
});
