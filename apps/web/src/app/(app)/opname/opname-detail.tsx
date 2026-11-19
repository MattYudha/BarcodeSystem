"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ScanBarcode, Trash2, XCircle } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { CameraScanner } from "@/components/app/camera-scanner";
import { EmptyState, ErrorBlock, LoadingBlock } from "@/components/app/common";
import { Confirm } from "@/components/app/confirm";
import { VariantSearch } from "@/components/app/variant-search";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, api, errorMessage, unwrap, type Schemas } from "@/lib/api/client";
import { fmtDateTime, variantLabel } from "@/lib/format";
import { beepError, beepSuccess } from "@/lib/scan/feedback";
import { useKeyboardWedge } from "@/lib/scan/use-keyboard-wedge";
import { cn } from "@/lib/utils";

type Opname = Schemas["OpnameOut"];
type Item = Schemas["OpnameItemOut"];

export const opnameKey = (id: number) => ["opname", id] as const;

const STATUS = { draft: "Berjalan", finalized: "Selesai", cancelled: "Dibatalkan" } as const;

export function OpnameStatusBadge({ status }: { status: Opname["status"] }) {
  return (
    <Badge variant={status === "draft" ? "default" : "secondary"}
      className={status === "finalized" ? "bg-emerald-50 text-emerald-700" : undefined}>
      {STATUS[status]}
    </Badge>
  );
}

function CountInput({ opnameId, item, disabled }: { opnameId: number; item: Item; disabled: boolean }) {
  const qc = useQueryClient();
  // Komponen di-key dengan counted_qty -> nilai awal selalu sinkron dengan server tanpa effect.
  const [value, setValue] = useState(String(item.counted_qty));
  const save = useMutation({
    mutationFn: (qty: number) =>
      unwrap<Opname>(api.PUT("/api/v1/opnames/{opname_id}/items", {
        params: { path: { opname_id: opnameId } },
        body: { items: [{ variant_id: item.variant.id, counted_qty: qty }] },
      })),
    onSuccess: (o) => qc.setQueryData(opnameKey(opnameId), o),
    onError: () => setValue(String(item.counted_qty)),
  });
  const commit = () => {
    const n = Number(value);
    if (!Number.isInteger(n) || n < 0) return setValue(String(item.counted_qty));
    if (n !== item.counted_qty) save.mutate(n);
  };
  return (
    <Input type="number" min={0} inputMode="numeric" className="h-8 w-20 text-right tabular-nums" disabled={disabled}
      aria-label={`Jumlah fisik ${item.variant.barcode}`} value={value}
      onChange={(e) => setValue(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />
  );
}

export function OpnameDetail({ id }: { id: number }) {
  const qc = useQueryClient();
  const opname = useQuery({
    queryKey: opnameKey(id),
    queryFn: () => unwrap<Opname>(api.GET("/api/v1/opnames/{opname_id}", { params: { path: { opname_id: id } } })),
  });
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null);
  const [manual, setManual] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const draft = opname.data?.status === "draft";

  const scan = useCallback(async (raw: string) => {
    const barcode = raw.trim().toUpperCase();
    if (!barcode) return;
    try {
      const item = await unwrap<Item>(api.POST("/api/v1/opnames/{opname_id}/scan", {
        params: { path: { opname_id: id } }, body: { barcode, increment: 1 },
      }));
      beepSuccess();
      setLast({ ok: true, text: `${item.variant.product_name} (${variantLabel(item.variant)}) → dihitung ${item.counted_qty}` });
      await qc.invalidateQueries({ queryKey: opnameKey(id) });
    } catch (err) {
      beepError();
      setLast({ ok: false, text: err instanceof ApiError && err.code === "VARIANT_NOT_FOUND" ? `Barcode tidak dikenal: ${barcode}` : errorMessage(err) });
    }
  }, [id, qc]);

  useKeyboardWedge((c) => { setManual(""); void scan(c); }, draft, input);

  const setCount = useMutation({
    mutationFn: (variantId: number) =>
      unwrap<Opname>(api.PUT("/api/v1/opnames/{opname_id}/items", {
        params: { path: { opname_id: id } }, body: { items: [{ variant_id: variantId, counted_qty: 0 }] },
      })),
    onSuccess: (o) => qc.setQueryData(opnameKey(id), o),
  });

  if (opname.isPending) return <LoadingBlock />;
  if (opname.isError) return <ErrorBlock error={opname.error} onRetry={() => opname.refetch()} />;
  const o = opname.data;
  const diffs = o.items.filter((i) => i.diff !== 0);

  const close = (action: "finalize" | "cancel") =>
    unwrap<Opname>(api.POST(action === "finalize" ? "/api/v1/opnames/{opname_id}/finalize" : "/api/v1/opnames/{opname_id}/cancel",
      { params: { path: { opname_id: id } } }))
      .then(async (res) => {
        qc.setQueryData(opnameKey(id), res);
        await qc.invalidateQueries();
        toast.success(action === "finalize"
          ? `Stock opname ${res.code} selesai. ${res.diff_count} varian disesuaikan.`
          : `Stock opname ${res.code} dibatalkan.`);
      });

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <OpnameStatusBadge status={o.status} />
        <span>Dimulai {fmtDateTime(o.created_at)} oleh {o.created_by.name}</span>
        {o.finalized_at && <span>· selesai {fmtDateTime(o.finalized_at)} oleh {o.finalized_by?.name}</span>}
        {o.note && <span>· {o.note}</span>}
      </div>

      {draft && (
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
          <Card>
            <CardHeader><CardTitle>Hitung barang</CardTitle></CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm text-muted-foreground">Setiap scan menambah jumlah fisik +1. Jumlah juga bisa diketik langsung di tabel.</p>
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void scan(manual); setManual(""); }}>
                <div className="relative flex-1">
                  <ScanBarcode className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input ref={input} autoFocus className="pl-8 font-mono" placeholder="Scan / ketik barcode" aria-label="Barcode opname"
                    value={manual} onChange={(e) => setManual(e.target.value)} autoComplete="off" />
                </div>
                <Button type="submit" disabled={!manual.trim()}>+1</Button>
              </form>
              <CameraScanner onScan={(c) => void scan(c)} />
              {last && (
                <p className={cn("flex items-start gap-2 text-sm", last.ok ? "text-emerald-700" : "text-red-700")} role="status" data-testid="opname-last">
                  {last.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : <XCircle className="mt-0.5 size-4 shrink-0" />} {last.text}
                </p>
              )}
              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">Barang tanpa label / tidak ada fisiknya:</span>
                <VariantSearch archived="all" placeholder="Cari lalu catat jumlah fisik…"
                  exclude={new Set(o.items.map((i) => i.variant.id))} onPick={(v) => setCount.mutate(v.id)} />
              </div>
            </CardContent>
          </Card>

          <Card className="h-fit">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
              <CardTitle>{o.item_count} varian dihitung · {diffs.length} selisih</CardTitle>
              <div className="flex gap-2">
                <Confirm title="Batalkan stock opname?" description="Hitungan dibuang dan stok tidak berubah." confirmLabel="Batalkan opname"
                  onConfirm={() => close("cancel")} trigger={<Button variant="outline">Batalkan</Button>} />
                <Confirm
                  title="Selesaikan stock opname?"
                  description={
                    <>
                      <p>Selisih dihitung terhadap stok sistem <b>saat ini</b> dan dicatat sebagai transaksi penyesuaian.
                        Varian yang tidak dihitung tidak berubah.</p>
                      <p className="mt-2">{diffs.length} varian akan disesuaikan.</p>
                    </>
                  }
                  confirmLabel="Selesaikan"
                  onConfirm={() => close("finalize")}
                  trigger={<Button disabled={!o.item_count}>Selesaikan opname</Button>}
                />
              </div>
            </CardHeader>
            <CardContent className="px-0">
              <OpnameItemsTable opname={o} editable />
            </CardContent>
          </Card>
        </div>
      )}

      {!draft && (
        <Card className="p-0">
          <OpnameItemsTable opname={o} editable={false} />
        </Card>
      )}
    </div>
  );
}

function OpnameItemsTable({ opname, editable }: { opname: Opname; editable: boolean }) {
  const qc = useQueryClient();
  if (!opname.items.length) return <EmptyState title="Belum ada barang yang dihitung" description="Mulai scan barang di rak." />;
  const remove = (variantId: number) =>
    unwrap(api.DELETE("/api/v1/opnames/{opname_id}/items/{variant_id}", { params: { path: { opname_id: opname.id, variant_id: variantId } } }))
      .then(() => qc.invalidateQueries({ queryKey: opnameKey(opname.id) }))
      .catch((e: Error) => toast.error(e.message));
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="pl-6">Barang</TableHead>
          <TableHead className="text-right">Fisik</TableHead>
          <TableHead className="text-right">{opname.status === "finalized" ? "Stok saat selesai" : "Stok sistem"}</TableHead>
          <TableHead className="text-right">Selisih</TableHead>
          {editable && <TableHead className="w-10 pr-6" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {opname.items.map((i) => (
          <TableRow key={i.variant.id} data-testid="opname-item" data-barcode={i.variant.barcode}>
            <TableCell className="pl-6">
              <span className="font-medium">{i.variant.product_name}</span>
              <span className="block text-xs text-muted-foreground">{variantLabel(i.variant)} · <span className="font-mono">{i.variant.barcode}</span></span>
            </TableCell>
            <TableCell className="text-right">
              {editable ? <div className="flex justify-end"><CountInput key={`${i.variant.id}-${i.counted_qty}`} opnameId={opname.id} item={i} disabled={false} /></div>
                : <span className="tabular-nums">{i.counted_qty}</span>}
            </TableCell>
            <TableCell className="text-right tabular-nums">{i.current_stock}</TableCell>
            <TableCell data-testid="opname-diff"
              className={cn("text-right font-semibold tabular-nums", i.diff > 0 && "text-emerald-700", i.diff < 0 && "text-red-700")}>
              {i.diff > 0 ? `+${i.diff}` : i.diff}
            </TableCell>
            {editable && (
              <TableCell className="pr-6">
                <Button variant="ghost" size="icon-sm" aria-label={`Hapus hitungan ${i.variant.barcode}`} onClick={() => remove(i.variant.id)}><Trash2 /></Button>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
