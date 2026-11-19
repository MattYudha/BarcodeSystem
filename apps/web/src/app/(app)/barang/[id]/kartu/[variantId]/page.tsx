"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useState } from "react";

import { EmptyState, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { MovementTable } from "@/components/app/movement-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { fmtDate, num, todayWib, variantLabel } from "@/lib/format";

function daysAgo(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d - n));
  return dt.toISOString().slice(0, 10);
}

function StockCard() {
  const { id, variantId } = useParams<{ id: string; variantId: string }>();
  const today = todayWib();
  const [from, setFrom] = useState(daysAgo(today, 29));
  const [to, setTo] = useState(today);
  const card = useQuery({
    queryKey: ["stock-card", Number(variantId), from, to],
    queryFn: () =>
      unwrap<Schemas["StockCardOut"]>(
        api.GET("/api/v1/variants/{variant_id}/stock-card", {
          params: { path: { variant_id: Number(variantId) }, query: { date_from: from, date_to: to } },
        }),
      ),
    enabled: !!from && !!to && from <= to,
  });

  const stat = (label: string, value: number, sign = false) => (
    <Card className="gap-1 py-3">
      <CardContent className="px-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-lg font-semibold tabular-nums">{sign && value > 0 ? `+${num(value)}` : num(value)}</p>
      </CardContent>
    </Card>
  );

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href={`/barang/${id}`}><ArrowLeft /> Kembali ke barang</Link>
      </Button>
      <PageHeader
        title="Kartu Stok"
        description={card.data && (
          <>
            {card.data.variant.product_name} · {variantLabel(card.data.variant)} ·{" "}
            <span className="font-mono">{card.data.variant.barcode}</span> · stok saat ini{" "}
            <b>{card.data.current_stock}</b>
          </>
        )}
      />
      <Card className="mb-4 flex flex-row flex-wrap items-end gap-3 p-3 print:hidden">
        <div className="grid gap-1">
          <Label htmlFor="from" className="text-xs">Dari</Label>
          <Input id="from" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="to" className="text-xs">Sampai</Label>
          <Input id="to" type="date" value={to} min={from} max={today} onChange={(e) => setTo(e.target.value)} />
        </div>
      </Card>

      {card.isPending ? (
        <LoadingBlock />
      ) : card.isError ? (
        <ErrorBlock error={card.error} onRetry={() => card.refetch()} />
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" data-testid="stock-card-totals">
            {stat(`Saldo awal ${fmtDate(card.data.period_from)}`, card.data.opening_balance)}
            {stat("Masuk", card.data.total_in)}
            {stat("Keluar", card.data.total_out)}
            {stat("Penyesuaian", card.data.total_adjust, true)}
            {stat("Pembatalan", card.data.total_reversal, true)}
            {stat(`Saldo akhir ${fmtDate(card.data.period_to)}`, card.data.closing_balance)}
          </div>
          {card.data.truncated && (
            <p className="text-sm text-amber-700">Transaksi terlalu banyak untuk ditampilkan semua. Persempit rentang tanggal.</p>
          )}
          <Card className="p-0">
            {card.data.movements.length ? (
              <MovementTable movements={card.data.movements} showProduct={false} />
            ) : (
              <EmptyState title="Tidak ada transaksi pada periode ini" />
            )}
          </Card>
        </div>
      )}
    </>
  );
}

export default function StockCardPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <StockCard />
    </Suspense>
  );
}
