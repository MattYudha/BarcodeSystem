"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Loader2, Printer } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AdminOnly, EmptyState, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { MovementTable } from "@/components/app/movement-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, fetchBlob, unwrap, type Schemas } from "@/lib/api/client";
import { useCategories } from "@/lib/catalog";
import { MOVEMENT_TYPES, num, todayWib, variantLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

type Period = "day" | "week" | "month" | "range";
type MovementType = keyof typeof MOVEMENT_TYPES;
const ALL = "all";
const PAGE_SIZE = 100;

function signed(n: number) {
  return n > 0 ? `+${num(n)}` : num(n);
}

function ReportPage() {
  const today = todayWib();
  const categories = useCategories(true);
  const [period, setPeriod] = useState<Period>("day");
  const [date, setDate] = useState(today);
  const [from, setFrom] = useState(today.slice(0, 8) + "01");
  const [to, setTo] = useState(today);
  const [category, setCategory] = useState(ALL);
  const [type, setType] = useState<MovementType | typeof ALL>(ALL);
  const [page, setPage] = useState(1);
  const [downloading, setDownloading] = useState<string | null>(null);

  const base = {
    period,
    ...(period === "range" ? { date_from: from, date_to: to } : { date }),
    ...(category !== ALL ? { category_id: Number(category) } : {}),
  };
  const valid = period !== "range" || (!!from && !!to && from <= to);

  const summary = useQuery({
    queryKey: ["report-summary", base],
    queryFn: () => unwrap<Schemas["ReportSummaryOut"]>(api.GET("/api/v1/reports/summary", { params: { query: base } })),
    enabled: valid,
    placeholderData: keepPreviousData,
  });
  const txQuery = { ...base, ...(type !== ALL ? { type: [type] } : {}), page, page_size: PAGE_SIZE };
  const movements = useQuery({
    queryKey: ["report-movements", txQuery],
    queryFn: () => unwrap<Schemas["Page_MovementOut_"]>(api.GET("/api/v1/reports/movements", { params: { query: txQuery } })),
    enabled: valid,
    placeholderData: keepPreviousData,
  });

  function qs(extra: Record<string, string | number | undefined> = {}) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...base, ...extra })) if (v !== undefined) p.set(k, String(v));
    return p.toString();
  }

  async function download(kind: "summary" | "movements" | "stock") {
    setDownloading(kind);
    try {
      const url = kind === "stock"
        ? `/api/v1/reports/stock.csv${category !== ALL ? `?category_id=${category}` : ""}`
        : `/api/v1/reports/${kind}.csv?${qs(kind === "movements" && type !== ALL ? { type } : {})}`;
      const { blob, filename } = await fetchBlob(url);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename ?? `${kind}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDownloading(null);
    }
  }

  const s = summary.data;
  const totalPages = movements.data ? Math.max(1, Math.ceil(movements.data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <PageHeader
        title="Laporan"
        description={s ? <>Periode <b data-testid="period-label">{s.period.label}</b> · waktu WIB</> : "Ringkasan stok & transaksi per periode."}
        actions={
          <div className="flex gap-2 print:hidden">
            <Button variant="outline" onClick={() => window.print()}><Printer /> Cetak</Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button disabled={!!downloading}>
                  {downloading ? <Loader2 className="animate-spin" /> : <Download />} Unduh CSV
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => download("summary")}>Ringkasan per barang</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => download("movements")}>Daftar transaksi</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => download("stock")}>Posisi stok saat ini</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />

      <Card className="mb-4 grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-4 print:hidden">
        <div className="grid gap-1">
          <Label className="text-xs">Periode</Label>
          <Select value={period} onValueChange={(v) => { setPeriod(v as Period); setPage(1); }}>
            <SelectTrigger className="w-full" aria-label="Periode"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="day">Harian</SelectItem>
              <SelectItem value="week">Mingguan (Senin–Minggu)</SelectItem>
              <SelectItem value="month">Bulanan</SelectItem>
              <SelectItem value="range">Rentang tanggal</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {period === "range" ? (
          <>
            <div className="grid gap-1">
              <Label htmlFor="r-from" className="text-xs">Dari</Label>
              <Input id="r-from" type="date" value={from} max={to} onChange={(e) => { setFrom(e.target.value); setPage(1); }} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="r-to" className="text-xs">Sampai</Label>
              <Input id="r-to" type="date" value={to} min={from} onChange={(e) => { setTo(e.target.value); setPage(1); }} />
            </div>
          </>
        ) : (
          <div className="grid gap-1">
            <Label htmlFor="r-date" className="text-xs">{period === "day" ? "Tanggal" : "Tanggal di dalam periode"}</Label>
            <Input id="r-date" type="date" value={date} onChange={(e) => { setDate(e.target.value); setPage(1); }} />
          </div>
        )}
        <div className="grid gap-1">
          <Label className="text-xs">Kategori</Label>
          <Select value={category} onValueChange={(v) => { setCategory(v); setPage(1); }}>
            <SelectTrigger className="w-full" aria-label="Kategori laporan"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Semua kategori</SelectItem>
              {categories.data?.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </Card>

      {!valid ? (
        <p className="text-sm text-destructive">Tanggal &quot;sampai&quot; tidak boleh sebelum &quot;dari&quot;.</p>
      ) : summary.isPending ? (
        <LoadingBlock />
      ) : summary.isError ? (
        <ErrorBlock error={summary.error} onRetry={() => summary.refetch()} />
      ) : (
        <div className={cn("grid gap-4", summary.isFetching && "opacity-70")}>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" data-testid="report-totals">
            {[
              ["Masuk", s!.totals.qty_in, "text-emerald-700"],
              ["Keluar", s!.totals.qty_out, "text-sky-700"],
              ["Penyesuaian", s!.totals.qty_adjust, "text-violet-700"],
              ["Pembatalan", s!.totals.qty_reversal, "text-zinc-600"],
              ["Transaksi", s!.totals.tx_count, ""],
            ].map(([label, value, tone]) => (
              <Card key={label as string} className="gap-1 py-3">
                <CardContent className="px-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className={cn("text-2xl font-semibold tabular-nums", tone as string)} data-testid={`total-${label}`}>
                    {label === "Penyesuaian" || label === "Pembatalan" ? signed(value as number) : num(value as number)}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Tabs defaultValue="summary">
            <TabsList className="print:hidden">
              <TabsTrigger value="summary">Ringkasan per barang</TabsTrigger>
              <TabsTrigger value="movements">Daftar transaksi</TabsTrigger>
            </TabsList>
            <TabsContent value="summary">
              <Card className="p-0">
                {s!.rows.length === 0 ? (
                  <EmptyState title="Tidak ada transaksi pada periode ini" />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Barang</TableHead>
                        <TableHead className="text-right">Saldo awal</TableHead>
                        <TableHead className="text-right">Masuk</TableHead>
                        <TableHead className="text-right">Keluar</TableHead>
                        <TableHead className="text-right">Penyesuaian</TableHead>
                        <TableHead className="text-right">Pembatalan</TableHead>
                        <TableHead className="pr-6 text-right">Saldo akhir</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {s!.rows.map((r) => (
                        <TableRow key={r.variant.id} data-testid="report-row" data-barcode={r.variant.barcode}>
                          <TableCell className="pl-6">
                            <span className="font-medium">{r.variant.product_name}</span>
                            <span className="block text-xs text-muted-foreground">{variantLabel(r.variant)} · <span className="font-mono">{r.variant.barcode}</span></span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{num(r.opening)}</TableCell>
                          <TableCell className="text-right tabular-nums text-emerald-700">{num(r.qty_in)}</TableCell>
                          <TableCell className="text-right tabular-nums text-sky-700">{num(r.qty_out)}</TableCell>
                          <TableCell className="text-right tabular-nums">{signed(r.qty_adjust)}</TableCell>
                          <TableCell className="text-right tabular-nums">{signed(r.qty_reversal)}</TableCell>
                          <TableCell className="pr-6 text-right font-semibold tabular-nums">{num(r.closing)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                    <TableFooter>
                      <TableRow>
                        <TableCell className="pl-6">Total ({s!.totals.variant_count} varian)</TableCell>
                        <TableCell />
                        <TableCell className="text-right tabular-nums">{num(s!.totals.qty_in)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(s!.totals.qty_out)}</TableCell>
                        <TableCell className="text-right tabular-nums">{signed(s!.totals.qty_adjust)}</TableCell>
                        <TableCell className="text-right tabular-nums">{signed(s!.totals.qty_reversal)}</TableCell>
                        <TableCell className="pr-6" />
                      </TableRow>
                    </TableFooter>
                  </Table>
                )}
              </Card>
            </TabsContent>
            <TabsContent value="movements" className="grid gap-3">
              <div className="flex items-center gap-2 print:hidden">
                <Label className="text-sm">Tipe</Label>
                <Select value={type} onValueChange={(v) => { setType(v as MovementType | typeof ALL); setPage(1); }}>
                  <SelectTrigger className="w-48" aria-label="Filter tipe transaksi"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Semua tipe</SelectItem>
                    {(Object.keys(MOVEMENT_TYPES) as MovementType[]).map((t) => (
                      <SelectItem key={t} value={t}>{MOVEMENT_TYPES[t]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Card className="p-0">
                {movements.isPending ? <LoadingBlock /> : movements.isError ? (
                  <ErrorBlock error={movements.error} onRetry={() => movements.refetch()} />
                ) : movements.data.items.length === 0 ? (
                  <EmptyState title="Tidak ada transaksi" />
                ) : (
                  <>
                    <MovementTable movements={movements.data.items} />
                    <div className="flex items-center justify-between border-t px-4 py-2 text-sm text-muted-foreground print:hidden">
                      <span>{num(movements.data.total)} transaksi</span>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="icon-sm" aria-label="Halaman sebelumnya" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft /></Button>
                        <span className="tabular-nums">{page} / {totalPages}</span>
                        <Button variant="outline" size="icon-sm" aria-label="Halaman berikutnya" disabled={page >= totalPages} onClick={() => setPage(page + 1)}><ChevronRight /></Button>
                      </div>
                    </div>
                  </>
                )}
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </>
  );
}

export default function LaporanPage() {
  return (
    <AdminOnly>
      <ReportPage />
    </AdminOnly>
  );
}
