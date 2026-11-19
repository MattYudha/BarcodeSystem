/**
 * Keranjang scan (logika murni, tanpa React -> diuji unit test).
 *
 * Aturan:
 * - Scan barcode yang sama -> jumlah baris yang ada +1 (mode keranjang); mode per-item mengganti item.
 * - Setiap perubahan isi keranjang membuat Idempotency-Key BARU. Mengirim ulang keranjang yang
 *   sama persis (mis. jaringan putus) memakai kunci yang sama -> server tidak mencatat ganda.
 * - Keluar: alasan wajib; "lainnya" wajib catatan; jumlah tidak boleh melebihi stok yang diketahui.
 */

import type { Schemas, Variant } from "@/lib/api/client";

export type Mode = "IN" | "OUT";
export type OutReason = "sale" | "return_to_production" | "damaged" | "other";
export type ScanSource = "scanner" | "camera" | "manual";

export type Line = {
  variant: Variant;
  qty: number;
  reason: OutReason | null;
  production_date: string;
  batch_code: string;
  note: string;
};

export type Defaults = { reason: OutReason; production_date: string; batch_code: string };

export type Cart = {
  mode: Mode;
  lines: Line[];
  source: ScanSource;
  key: string;
};

export type Action =
  | { type: "scan"; variant: Variant; source: ScanSource; single: boolean; defaults: Defaults }
  | { type: "qty"; variantId: number; qty: number }
  | { type: "field"; variantId: number; patch: Partial<Pick<Line, "reason" | "production_date" | "batch_code" | "note">> }
  | { type: "remove"; variantId: number }
  | { type: "clear" }
  | { type: "mode"; mode: Mode };

export const MAX_QTY = 100_000;

export function emptyCart(mode: Mode, key: string): Cart {
  return { mode, lines: [], source: "scanner", key };
}

const clampQty = (n: number) => Math.min(MAX_QTY, Math.max(1, Math.floor(Number.isFinite(n) ? n : 1)));

/** `newKey` disuntik agar reducer tetap murni & bisa diuji. */
export function reduce(cart: Cart, action: Action, newKey: () => string): Cart {
  const touch = (c: Omit<Cart, "key">): Cart => ({ ...c, key: newKey() });
  switch (action.type) {
    case "scan": {
      const source: ScanSource = action.source === "camera" || cart.source === "camera" ? "camera" : action.source;
      const existing = cart.lines.find((l) => l.variant.id === action.variant.id);
      if (existing && !action.single) {
        return touch({
          ...cart,
          source,
          lines: cart.lines.map((l) =>
            l.variant.id === action.variant.id ? { ...l, variant: action.variant, qty: clampQty(l.qty + 1) } : l,
          ),
        });
      }
      const line: Line = {
        variant: action.variant,
        qty: 1,
        reason: cart.mode === "OUT" ? action.defaults.reason : null,
        production_date: cart.mode === "IN" ? action.defaults.production_date : "",
        batch_code: cart.mode === "IN" ? action.defaults.batch_code : "",
        note: "",
      };
      return touch({ ...cart, source, lines: action.single ? [line] : [...cart.lines, line] });
    }
    case "qty":
      return touch({
        ...cart,
        lines: cart.lines.map((l) => (l.variant.id === action.variantId ? { ...l, qty: clampQty(action.qty) } : l)),
      });
    case "field":
      return touch({
        ...cart,
        lines: cart.lines.map((l) => (l.variant.id === action.variantId ? { ...l, ...action.patch } : l)),
      });
    case "remove":
      return touch({ ...cart, lines: cart.lines.filter((l) => l.variant.id !== action.variantId) });
    case "clear":
      return touch({ ...cart, lines: [], source: "scanner" });
    case "mode":
      if (cart.lines.length) return cart; // ganti mode hanya saat keranjang kosong
      return touch({ ...cart, mode: action.mode });
  }
}

export type LineIssue = string | null;

export function lineIssue(cart: Cart, line: Line): LineIssue {
  if (cart.mode === "OUT") {
    if (!line.reason) return "Pilih alasan keluar";
    if (line.reason === "other" && !line.note.trim()) return "Isi catatan untuk alasan lainnya";
    if (line.qty > line.variant.stock) return `Melebihi stok (tersedia ${line.variant.stock})`;
  }
  return null;
}

export function cartIssues(cart: Cart): string[] {
  return cart.lines.flatMap((l) => {
    const issue = lineIssue(cart, l);
    return issue ? [`${l.variant.product_name} (${l.variant.size}): ${issue}`] : [];
  });
}

export function totalQty(cart: Cart): number {
  return cart.lines.reduce((s, l) => s + l.qty, 0);
}

export function toRequest(cart: Cart): Schemas["MovementCreateIn"] {
  return {
    type: cart.mode,
    source: cart.source,
    lines: cart.lines.map((l) => ({
      variant_id: l.variant.id,
      qty: l.qty,
      reason: cart.mode === "OUT" ? l.reason : null,
      production_date: cart.mode === "IN" && l.production_date ? l.production_date : null,
      batch_code: cart.mode === "IN" && l.batch_code.trim() ? l.batch_code.trim() : null,
      note: l.note.trim() || null,
    })),
  };
}
