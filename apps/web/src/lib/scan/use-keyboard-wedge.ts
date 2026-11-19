"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * Scanner USB/Bluetooth (mode keyboard) "mengetik" barcode sangat cepat lalu menekan Enter.
 *
 * Hook ini adalah SATU-SATUNYA penerima scan dari scanner:
 * - Ketikan cepat (jeda antar karakter < 60 ms) diakumulasi, baik saat fokus di halaman maupun di
 *   kolom barcode (`scanInput`). Saat Enter, seluruh burst dikirim sebagai satu scan utuh —
 *   walaupun fokus berpindah di tengah scan (mis. kolom barcode di-fokus ulang setelah Simpan).
 *   Tanpa ini, satu barcode bisa terpecah: sebagian ke halaman, sebagian ke kolom.
 * - Ketikan manual yang lambat di kolom barcode dibiarkan; Enter men-submit form seperti biasa.
 * - Kolom isian lain (jumlah, catatan, dll.) tidak disentuh.
 */
const MAX_INTERVAL_MS = 60; // jeda antar karakter scanner biasanya < 30 ms
const MIN_LENGTH = 4;

function isOtherEditable(el: Element | null, scanInput: HTMLElement | null): boolean {
  if (!el || el === scanInput) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable
  );
}

export function useKeyboardWedge(
  onScan: (code: string) => void,
  enabled = true,
  scanInput?: RefObject<HTMLInputElement | null>,
) {
  const handler = useRef(onScan);
  useEffect(() => {
    handler.current = onScan;
  }, [onScan]);

  useEffect(() => {
    if (!enabled) return;
    let buffer = "";
    let last = 0;

    function onKeyDown(e: KeyboardEvent) {
      const field = scanInput?.current ?? null;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (isOtherEditable(document.activeElement, field)) {
        buffer = "";
        return;
      }
      const now = performance.now();
      if (now - last > MAX_INTERVAL_MS) buffer = "";
      last = now;
      if (e.key === "Enter") {
        if (buffer.length >= MIN_LENGTH) {
          // burst scanner: proses di sini, cegah submit form dengan isi kolom yang mungkin terpotong
          e.preventDefault();
          e.stopPropagation();
          const code = buffer;
          buffer = "";
          handler.current(code);
        }
        buffer = "";
        return;
      }
      if (e.key.length === 1) buffer += e.key;
    }

    // capture: berjalan sebelum handler form/kolom
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [enabled, scanInput]);
}
