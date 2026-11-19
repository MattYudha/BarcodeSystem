"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CheckCircle2,
  Loader2,
  Minus,
  Plus,
  ScanBarcode,
  Tags,
  Trash2,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";

import { CameraScanner } from "@/components/app/camera-scanner";
import { PageHeader } from "@/components/app/common";
import { MovementTypeBadge } from "@/components/app/movement";
import { ReverseButton } from "@/components/app/reverse-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, api, errorMessage, unwrap, uuid, type Movement, type Schemas, type Variant } from "@/lib/api/client";
import { fmtDateTime, OUT_REASONS, todayWib, variantLabel } from "@/lib/format";
import {
  cartIssues,
  emptyCart,
  lineIssue,
  reduce,
  toRequest,
  totalQty,
  type Action,
  type Cart,
  type Defaults,
  type Mode,
  type OutReason,
  type ScanSource,
} from "@/lib/scan/cart";
import { beepError, beepSuccess, unlockAudio } from "@/lib/scan/feedback";
import { useKeyboardWedge } from "@/lib/scan/use-keyboard-wedge";
import { useIsAdmin } from "@/lib/session";
import { cn } from "@/lib/utils";

type LogEntry = { id: number; code: string; ok: boolean; text: string };
type Flash = "ok" | "error" | null;

function cartReducer(cart: Cart, action: Action) {
  return reduce(cart, action, uuid);
}

function ModeToggle({ mode, disabled, onChange }: { mode: Mode; disabled: boolean; onChange: (m: Mode) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Mode transaksi">
      {(["IN", "OUT"] as const).map((m) => {
        const active = mode === m;
        const Icon = m === "IN" ? ArrowDownToLine : ArrowUpFromLine;
        return (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled && !active}
            onClick={() => onChange(m)}
            className={cn(
              "flex items-center justify-center gap-2 rounded-xl border-2 px-4 py-3 text-base font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              active && m === "IN" && "border-emerald-600 bg-emerald-600 text-white",
              active && m === "OUT" && "border-sky-600 bg-sky-600 text-white",
              !active && "bg-background text-muted-foreground hover:bg-muted",
            )}
          >
            <Icon className="size-5" /> {m === "IN" ? "Barang masuk" : "Barang keluar"}
          </button>
        );
      })}
    </div>
  );
}

function ReasonSelect({ value, onChange, label }: { value: OutReason | null; onChange: (r: OutReason) => void; label: string }) {
  return (
    <Select value={value ?? undefined} onValueChange={(v) => onChange(v as OutReason)}>
      <SelectTrigger className="w-full" aria-label={label}><SelectValue placeholder="Pilih alasan" /></SelectTrigger>
      <SelectContent>
        {(Object.keys(OUT_REASONS) as OutReason[]).map((r) => (
          <SelectItem key={r} value={r}>{OUT_REASONS[r]}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function ScanPage() {
  const qc = useQueryClient();
  const isAdmin = useIsAdmin();
  const [cart, dispatch] = useReducer(cartReducer, undefined, () => emptyCart("IN", uuid()));
  const [single, setSingle] = useState(false);
  const [defaults, setDefaults] = useState<Defaults>({ reason: "sale", production_date: "", batch_code: "" });
  const [log, setLog] = useState<LogEntry[]>([]);
  const [flash, setFlash] = useState<Flash>(null);
  const [lastSaved, setLastSaved] = useState<Movement[] | null>(null);
  const [manual, setManual] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const pending = useRef(new Set<string>());
  const logId = useRef(0);

  const focusInput = useCallback(() => setTimeout(() => input.current?.focus(), 0), []);
  useEffect(() => { focusInput(); }, [focusInput]);

  function addLog(code: string, ok: boolean, text: string) {
    setLog((xs) => [{ id: ++logId.current, code, ok, text }, ...xs].slice(0, 6));
    setFlash(ok ? "ok" : "error");
    setTimeout(() => setFlash(null), 600);
    if (ok) beepSuccess(); else beepError();
  }

  const handleScan = useCallback(async (raw: string, source: ScanSource) => {
    const code = raw.trim().toUpperCase();
    if (!code || pending.current.has(code)) return;
    pending.current.add(code);
    try {
      const v = await unwrap<Variant>(api.GET("/api/v1/variants/lookup", { params: { query: { barcode: code } } }));
      dispatch({ type: "scan", variant: v, source, single, defaults });
      setLastSaved(null);
      addLog(code, true, `${v.product_name} · ${variantLabel(v)}`);
    } catch (err) {
      // Barcode tak dikenal / arsip: pesan jelas, tidak ada transaksi (aturan PRD).
      const msg = err instanceof ApiError && err.code === "VARIANT_NOT_FOUND" ? "Barcode tidak dikenal" : errorMessage(err);
      addLog(code, false, msg);
    } finally {
      pending.current.delete(code);
    }
  }, [single, defaults]);

  // Semua scan dari scanner (di kolom barcode maupun di halaman) lewat satu jalur.
  useKeyboardWedge((code) => { setManual(""); void handleScan(code, "scanner"); }, true, input);

  const issues = cartIssues(cart);
  const save = useMutation({
    mutationFn: () =>
      unwrap<Schemas["MovementGroupOut"]>(
        api.POST("/api/v1/movements", {
          params: { header: { "Idempotency-Key": cart.key } },
          body: toRequest(cart),
        }),
      ),
    onSuccess: async (res) => {
      const qty = res.movements.reduce((s, m) => s + Math.abs(m.qty), 0);
      toast.success(`${cart.mode === "IN" ? "Barang masuk" : "Barang keluar"} tersimpan: ${qty} pcs (${res.movements.length} varian).`);
      setLastSaved(res.movements);
      dispatch({ type: "clear" });
      await qc.invalidateQueries();
      focusInput();
    },
    onError: () => beepError(),
  });

  const recent = useQuery({
    queryKey: ["movements", "today"],
    queryFn: () =>
      unwrap<Schemas["Page_MovementOut_"]>(
        api.GET("/api/v1/movements", { params: { query: { date_from: todayWib(), page_size: 15 } } }),
      ),
  });

  const labelHref = lastSaved && lastSaved[0]?.type === "IN"
    ? `/label?items=${lastSaved.map((m) => `${m.variant.id}:${m.qty}`).join(",")}`
    : null;

  return (
    <div onClick={unlockAudio}>
      <PageHeader title="Scan Barang" description="Scan dengan scanner USB/Bluetooth atau kamera HP. Tekan Enter untuk barcode yang diketik." />

      <div className="grid gap-5 lg:grid-cols-[380px_1fr]">
        {/* ---------------------------------------------------------------- panel scan */}
        <div className="grid h-fit gap-4">
          <ModeToggle mode={cart.mode} disabled={cart.lines.length > 0}
            onChange={(m) => { dispatch({ type: "mode", mode: m }); focusInput(); }} />
          {cart.lines.length > 0 && (
            <p className="-mt-2 text-xs text-muted-foreground">Simpan atau kosongkan keranjang untuk mengganti mode.</p>
          )}

          <Card className={cn("transition-colors", flash === "ok" && "ring-4 ring-emerald-400", flash === "error" && "ring-4 ring-red-400")}>
            <CardContent className="grid gap-3">
              <Tabs value={single ? "single" : "cart"} onValueChange={(v) => { setSingle(v === "single"); dispatch({ type: "clear" }); focusInput(); }}>
                <TabsList className="w-full">
                  <TabsTrigger value="cart">Mode keranjang</TabsTrigger>
                  <TabsTrigger value="single">Per item</TabsTrigger>
                </TabsList>
              </Tabs>
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void handleScan(manual, "scanner"); setManual(""); }}>
                <div className="relative flex-1">
                  <ScanBarcode className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input ref={input} value={manual} onChange={(e) => setManual(e.target.value)}
                    className="h-10 pl-8 font-mono" placeholder="Arahkan scanner / ketik barcode"
                    aria-label="Barcode" autoComplete="off" autoCapitalize="characters" enterKeyHint="go" />
                </div>
                <Button type="submit" className="h-10" disabled={!manual.trim()}>Cari</Button>
              </form>
              <CameraScanner onScan={(code) => void handleScan(code, "camera")} />

              {cart.mode === "IN" ? (
                <div className="grid grid-cols-2 gap-2">
                  <div className="grid gap-1">
                    <Label htmlFor="def-date" className="text-xs text-muted-foreground">Tgl produksi (default)</Label>
                    <Input id="def-date" type="date" max={todayWib()} value={defaults.production_date}
                      onChange={(e) => setDefaults((d) => ({ ...d, production_date: e.target.value }))} />
                  </div>
                  <div className="grid gap-1">
                    <Label htmlFor="def-batch" className="text-xs text-muted-foreground">Batch (default)</Label>
                    <Input id="def-batch" maxLength={40} value={defaults.batch_code}
                      onChange={(e) => setDefaults((d) => ({ ...d, batch_code: e.target.value }))} />
                  </div>
                </div>
              ) : (
                <div className="grid gap-1">
                  <span className="text-xs text-muted-foreground">Alasan keluar (default)</span>
                  <ReasonSelect label="Alasan keluar default" value={defaults.reason}
                    onChange={(r) => setDefaults((d) => ({ ...d, reason: r }))} />
                </div>
              )}
            </CardContent>
          </Card>

          {log.length > 0 && (
            <Card className="gap-2 py-3">
              <CardContent className="px-4">
                <p className="mb-2 text-xs font-medium text-muted-foreground">Riwayat scan</p>
                <ul className="grid gap-1.5" data-testid="scan-log">
                  {log.map((l) => (
                    <li key={l.id} className="flex items-start gap-2 text-sm">
                      {l.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />}
                      <span className="min-w-0">
                        <span className="font-mono text-xs">{l.code}</span>
                        <span className={cn("block truncate", !l.ok && "text-red-700")}>{l.text}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ---------------------------------------------------------------- keranjang */}
        <div className="grid h-fit gap-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>
                {single ? "Item" : "Keranjang"} {cart.mode === "IN" ? "masuk" : "keluar"}
                {cart.lines.length > 0 && <Badge variant="secondary" className="ml-2" data-testid="cart-total">{totalQty(cart)} pcs</Badge>}
              </CardTitle>
              {cart.lines.length > 0 && (
                <Button variant="ghost" size="sm" onClick={() => { dispatch({ type: "clear" }); focusInput(); }}>Kosongkan</Button>
              )}
            </CardHeader>
            <CardContent className="grid gap-3">
              {cart.lines.length === 0 ? (
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">
                  <ScanBarcode className="size-8" />
                  Scan barcode untuk menambahkan barang.
                </div>
              ) : (
                <ul className="grid gap-2" data-testid="cart">
                  {cart.lines.map((l) => {
                    const issue = lineIssue(cart, l);
                    return (
                      <li key={l.variant.id} data-testid="cart-line" data-barcode={l.variant.barcode}
                        className={cn("grid gap-3 rounded-lg border p-3", issue && "border-red-300 bg-red-50/60")}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate font-medium">{l.variant.product_name}</p>
                            <p className="text-sm text-muted-foreground">
                              {variantLabel(l.variant)} · <span className="font-mono text-xs">{l.variant.barcode}</span> · stok {l.variant.stock}
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button variant="outline" size="icon-sm" aria-label="Kurangi" onClick={() => dispatch({ type: "qty", variantId: l.variant.id, qty: l.qty - 1 })}><Minus /></Button>
                            <Input type="number" min={1} inputMode="numeric" className="h-7 w-16 text-center tabular-nums"
                              aria-label={`Jumlah ${l.variant.barcode}`} value={l.qty}
                              onChange={(e) => dispatch({ type: "qty", variantId: l.variant.id, qty: Number(e.target.value) })}
                              onKeyDown={(e) => { if (e.key === "Enter" && single && !issues.length) save.mutate(); }} />
                            <Button variant="outline" size="icon-sm" aria-label="Tambah" onClick={() => dispatch({ type: "qty", variantId: l.variant.id, qty: l.qty + 1 })}><Plus /></Button>
                            <Button variant="ghost" size="icon-sm" aria-label={`Hapus ${l.variant.barcode}`} onClick={() => dispatch({ type: "remove", variantId: l.variant.id })}><Trash2 /></Button>
                          </div>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          {cart.mode === "OUT" ? (
                            <ReasonSelect label={`Alasan ${l.variant.barcode}`} value={l.reason}
                              onChange={(r) => dispatch({ type: "field", variantId: l.variant.id, patch: { reason: r } })} />
                          ) : (
                            <Input type="date" max={todayWib()} aria-label={`Tanggal produksi ${l.variant.barcode}`} value={l.production_date}
                              onChange={(e) => dispatch({ type: "field", variantId: l.variant.id, patch: { production_date: e.target.value } })} />
                          )}
                          <Input placeholder={cart.mode === "OUT" && l.reason === "other" ? "Catatan (wajib)" : "Catatan (opsional)"}
                            maxLength={500} aria-label={`Catatan ${l.variant.barcode}`} value={l.note}
                            onChange={(e) => dispatch({ type: "field", variantId: l.variant.id, patch: { note: e.target.value } })} />
                        </div>
                        {issue && <p className="text-sm font-medium text-red-700" role="alert">{issue}</p>}
                      </li>
                    );
                  })}
                </ul>
              )}
              <Button size="lg" className="h-12 text-base" disabled={!cart.lines.length || issues.length > 0 || save.isPending}
                onClick={() => save.mutate()}>
                {save.isPending && <Loader2 className="animate-spin" />}
                Simpan {cart.mode === "IN" ? "barang masuk" : "barang keluar"} {cart.lines.length > 0 && `(${totalQty(cart)} pcs)`}
              </Button>
            </CardContent>
          </Card>

          {lastSaved && (
            <Card className="border-emerald-200 bg-emerald-50/50" data-testid="last-saved">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-emerald-800"><CheckCircle2 className="size-5" /> Tersimpan</CardTitle>
                {labelHref && <Button size="sm" variant="outline" asChild><Link href={labelHref}><Tags /> Cetak label</Link></Button>}
              </CardHeader>
              <CardContent>
                <ul className="grid gap-1 text-sm">
                  {lastSaved.map((m) => (
                    <li key={m.id} className="flex items-center justify-between gap-2">
                      <span>{m.variant.product_name} ({variantLabel(m.variant)}) <b className="tabular-nums">{m.qty > 0 ? `+${m.qty}` : m.qty}</b> → stok {m.balance_after}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle>{isAdmin ? "Transaksi hari ini" : "Transaksi saya hari ini"}</CardTitle></CardHeader>
            <CardContent>
              {recent.data?.items.length ? (
                <ul className="divide-y" data-testid="recent-movements">
                  {recent.data.items.map((m) => (
                    <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                      <span className="w-12 shrink-0 text-xs text-muted-foreground tabular-nums">{fmtDateTime(m.created_at).slice(11)}</span>
                      <MovementTypeBadge movement={m} />
                      <span className="min-w-0 flex-1 truncate">{m.variant.product_name} ({variantLabel(m.variant)})</span>
                      <b className="tabular-nums">{m.qty > 0 ? `+${m.qty}` : m.qty}</b>
                      <ReverseButton movement={m} size="xs" />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">Belum ada transaksi hari ini.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
