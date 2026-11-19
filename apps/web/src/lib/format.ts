import { TZDate } from "@date-fns/tz";
import { format } from "date-fns";
import { id as localeId } from "date-fns/locale";

export const WIB = "Asia/Jakarta";

/** ISO UTC dari API -> "17/11/2026 14:05" (WIB). */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return format(new TZDate(iso, WIB), "dd/MM/yyyy HH:mm");
}

/** "2026-11-17" (tanggal murni) -> "17/11/2026". */
export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "-";
  const [y, m, d] = isoDate.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

/** Nama hari singkat untuk grafik, mis. "Sen 17/11". */
export function fmtDayShort(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return format(new Date(y, m - 1, d), "EEE dd/MM", { locale: localeId });
}

/** Tanggal hari ini menurut WIB, format YYYY-MM-DD (untuk input type=date & filter). */
export function todayWib(): string {
  return format(new TZDate(new Date(), WIB), "yyyy-MM-dd");
}

const rupiahFmt = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

export function rupiah(value: number | null | undefined): string {
  return value == null ? "-" : rupiahFmt.format(value);
}

const numFmt = new Intl.NumberFormat("id-ID");
export function num(value: number): string {
  return numFmt.format(value);
}

export function variantLabel(v: { size: string; color?: string | null }): string {
  return v.color ? `${v.size} · ${v.color}` : v.size;
}

export const OUT_REASONS = {
  sale: "Penjualan",
  return_to_production: "Retur ke produksi",
  damaged: "Rusak",
  other: "Lainnya",
} as const;

export const MOVEMENT_TYPES = {
  IN: "Masuk",
  OUT: "Keluar",
  ADJUST: "Penyesuaian",
  REVERSAL: "Pembatalan",
} as const;
