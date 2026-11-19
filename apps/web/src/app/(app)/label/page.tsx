"use client";

import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { Download, Loader2, Minus, Plus, Printer, Search, Tags, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, LoadingBlock, PageHeader } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useDebounced } from "@/hooks/use-debounced";
import { api, fetchBlob, unwrap, type Schemas, type Variant } from "@/lib/api/client";
import { num, variantLabel } from "@/lib/format";

const TEMPLATES = [
  { key: "a4_3x8", label: "Kertas stiker A4 — 24 label (70×36 mm)", perPage: 24 },
  { key: "a4_4x10", label: "Kertas stiker A4 — 40 label (48,5×25,4 mm)", perPage: 40 },
  { key: "thermal_50x30", label: "Printer label thermal 50×30 mm (203 dpi)", perPage: 1 },
  { key: "thermal_40x30", label: "Printer label thermal 40×30 mm (300 dpi)", perPage: 1 },
] as const;
type TemplateKey = (typeof TEMPLATES)[number]["key"];
const MAX_LABELS = 2000;

type Item = { variantId: number; copies: number };

function parseItems(raw: string | null): Item[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((part) => {
      const [id, copies] = part.split(":").map(Number);
      return { variantId: id, copies: Math.min(500, Math.max(1, copies || 1)) };
    })
    .filter((i) => Number.isInteger(i.variantId) && i.variantId > 0);
}

function VariantPicker({ onPick, exclude }: { onPick: (v: Variant) => void; exclude: Set<number> }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const results = useQuery({
    queryKey: ["variants", { q: dq, picker: true }],
    queryFn: () =>
      unwrap<Schemas["Page_VariantOut_"]>(
        api.GET("/api/v1/variants", { params: { query: { q: dq, page_size: 8 } } }),
      ),
    enabled: dq.length >= 2,
  });
  return (
    <div className="relative">
      <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
      <Input className="pl-8" placeholder="Cari barang / barcode untuk ditambahkan…" value={q}
        onChange={(e) => setQ(e.target.value)} aria-label="Cari varian" />
      {dq.length >= 2 && (
        <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border bg-popover shadow-md">
          {results.isPending ? (
            <p className="p-3 text-sm text-muted-foreground">Mencari…</p>
          ) : results.data?.items.length ? (
            results.data.items.map((v) => (
              <button key={v.id} type="button" disabled={exclude.has(v.id)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50"
                onClick={() => { onPick(v); setQ(""); }}>
                <span className="min-w-0">
                  <span className="block truncate font-medium">{v.product_name}</span>
                  <span className="text-xs text-muted-foreground">{variantLabel(v)} · {v.barcode}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">stok {v.stock}</span>
              </button>
            ))
          ) : (
            <p className="p-3 text-sm text-muted-foreground">Tidak ditemukan.</p>
          )}
        </div>
      )}
    </div>
  );
}

function LabelPrinter() {
  const params = useSearchParams();
  const [items, setItems] = useState<Item[]>(() => parseItems(params.get("items")));
  const [template, setTemplate] = useState<TemplateKey>("a4_3x8");
  const [showPrice, setShowPrice] = useState(false);
  const [startPos, setStartPos] = useState(1);
  const [preview, setPreview] = useState<{ url: string; filename: string } | null>(null);
  const iframe = useRef<HTMLIFrameElement>(null);

  // Detail varian untuk item yang datang dari URL (dan yang ditambahkan lewat pencarian).
  const details = useQueries({
    queries: items.map((it) => ({
      queryKey: ["variant", it.variantId],
      queryFn: () =>
        unwrap<Variant>(api.GET("/api/v1/variants/{variant_id}", { params: { path: { variant_id: it.variantId } } })),
      staleTime: 60_000,
    })),
  });
  const byId = new Map(details.flatMap((d) => (d.data ? [[d.data.id, d.data] as const] : [])));
  const total = items.reduce((s, i) => s + i.copies, 0);
  const tpl = TEMPLATES.find((t) => t.key === template)!;
  const pages = tpl.perPage === 1 ? total : Math.ceil((total + startPos - 1) / tpl.perPage);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);

  const generate = useMutation({
    mutationFn: () =>
      fetchBlob("/api/v1/labels/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template,
          show_price: showPrice,
          start_position: tpl.perPage > 1 ? startPos : 1,
          items: items.map((i) => ({ variant_id: i.variantId, copies: i.copies })),
        }),
      }),
    onSuccess: ({ blob, filename }) =>
      setPreview({ url: URL.createObjectURL(blob), filename: filename ?? "label.pdf" }),
  });

  const exclude = useMemo(() => new Set(items.map((i) => i.variantId)), [items]);
  const setCopies = (id: number, copies: number) =>
    setItems((xs) => xs.map((x) => (x.variantId === id ? { ...x, copies: Math.min(500, Math.max(1, copies || 1)) } : x)));

  return (
    <>
      <PageHeader title="Cetak Label" description="Label barcode Code 128 per varian, siap tempel." />
      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader>
            <CardTitle>Daftar label</CardTitle>
            <CardDescription>Jumlah salinan default = stok saat ini (satu label per barang).</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <VariantPicker exclude={exclude}
              onPick={(v) => setItems((xs) => [...xs, { variantId: v.id, copies: Math.max(1, v.stock) }])} />
            {items.length === 0 ? (
              <EmptyState title="Belum ada label dipilih"
                description="Cari barang di atas, atau buka halaman detail barang lalu pilih Cetak label." />
            ) : (
              <ul className="divide-y rounded-lg border" data-testid="label-items">
                {items.map((it, idx) => {
                  const v = byId.get(it.variantId);
                  const err = details[idx]?.isError;
                  return (
                    <li key={it.variantId} className="flex items-center gap-3 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        {v ? (
                          <>
                            <p className="truncate text-sm font-medium">{v.product_name}</p>
                            <p className="text-xs text-muted-foreground">
                              {variantLabel(v)} · <span className="font-mono">{v.barcode}</span> · stok {v.stock}
                            </p>
                          </>
                        ) : err ? (
                          <p className="text-sm text-destructive">Varian #{it.variantId} tidak ditemukan</p>
                        ) : (
                          <p className="text-sm text-muted-foreground">Memuat…</p>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <Button variant="outline" size="icon-sm" aria-label="Kurangi" onClick={() => setCopies(it.variantId, it.copies - 1)}><Minus /></Button>
                        <Input className="h-7 w-16 text-center tabular-nums" type="number" min={1} max={500}
                          aria-label={`Jumlah label ${v?.barcode ?? it.variantId}`}
                          value={it.copies} onChange={(e) => setCopies(it.variantId, Number(e.target.value))} />
                        <Button variant="outline" size="icon-sm" aria-label="Tambah" onClick={() => setCopies(it.variantId, it.copies + 1)}><Plus /></Button>
                      </div>
                      <Button variant="ghost" size="icon-sm" aria-label="Hapus dari daftar"
                        onClick={() => setItems((xs) => xs.filter((x) => x.variantId !== it.variantId))}><Trash2 /></Button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit lg:sticky lg:top-20">
          <CardHeader><CardTitle>Pengaturan cetak</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label>Jenis kertas / printer</Label>
              <Select value={template} onValueChange={(v) => setTemplate(v as TemplateKey)}>
                <SelectTrigger className="w-full" aria-label="Template label"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TEMPLATES.map((t) => <SelectItem key={t.key} value={t.key}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
              {tpl.perPage === 1 && (
                <p className="text-xs text-muted-foreground">
                  Saat mencetak, pilih ukuran kertas sesuai label dan skala 100% (jangan &quot;fit to page&quot;).
                </p>
              )}
            </div>
            {tpl.perPage > 1 && (
              <div className="grid gap-2">
                <Label htmlFor="start">Mulai dari stiker ke-</Label>
                <Input id="start" type="number" min={1} max={tpl.perPage} value={startPos}
                  onChange={(e) => setStartPos(Math.min(tpl.perPage, Math.max(1, Number(e.target.value) || 1)))} />
                <p className="text-xs text-muted-foreground">Untuk memakai sisa lembar stiker yang sudah terpakai sebagian.</p>
              </div>
            )}
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={showPrice} onCheckedChange={(c) => setShowPrice(c === true)} /> Tampilkan harga
            </label>
            <div className="rounded-lg bg-muted px-3 py-2 text-sm">
              <b className="tabular-nums">{num(total)}</b> label · ±{num(pages)} halaman
              {total > MAX_LABELS && <p className="text-destructive">Maksimal {num(MAX_LABELS)} label per cetak.</p>}
            </div>
            <Button size="lg" disabled={!items.length || total > MAX_LABELS || generate.isPending}
              onClick={() => generate.mutate()}>
              {generate.isPending ? <Loader2 className="animate-spin" /> : <Tags />} Buat PDF label
            </Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="flex h-[90dvh] flex-col sm:max-w-4xl">
          <DialogHeader><DialogTitle>Pratinjau label</DialogTitle></DialogHeader>
          {preview && (
            <iframe ref={iframe} src={preview.url} title="Pratinjau PDF label" className="min-h-0 flex-1 rounded-md border" />
          )}
          <DialogFooter>
            <Button variant="outline" asChild>
              <a href={preview?.url} download={preview?.filename}><Download /> Unduh PDF</a>
            </Button>
            <Button onClick={() => iframe.current?.contentWindow?.print()}><Printer /> Cetak</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function LabelPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <LabelPrinter />
    </Suspense>
  );
}
