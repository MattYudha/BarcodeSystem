"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDownToLine, ArrowUpFromLine, Boxes, Package } from "lucide-react";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { MovementTypeBadge } from "@/components/app/movement";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { fmtDateTime, fmtDayShort, num, variantLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function StatCard({
  label, value, icon: Icon, tone, testId,
}: {
  label: string; value: number; icon: typeof Package; tone?: string; testId: string;
}) {  // prettier-ignore
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex items-center gap-3 px-4">
        <span className={cn("flex size-10 items-center justify-center rounded-xl bg-muted", tone)}>
          <Icon className="size-5" />
        </span>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tabular-nums" data-testid={testId}>{num(value)}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => unwrap<Schemas["DashboardOut"]>(api.GET("/api/v1/dashboard")),
    refetchInterval: 60_000,
  });

  return (
    <>
      <PageHeader title="Dashboard" description="Ringkasan stok gudang hari ini (WIB)." />
      {q.isPending ? (
        <LoadingBlock />
      ) : q.isError ? (
        <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="grid gap-5">
          {q.data.alert_count > 0 && (
            <Link
              href="/barang?stock_status=alert"
              className="flex items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 hover:bg-amber-100"
            >
              <AlertTriangle className="size-5 shrink-0" />
              <span>
                <b>{q.data.alert_count} varian</b> stoknya menipis atau habis. Lihat daftar →
              </span>
            </Link>
          )}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatCard label="Jenis barang" value={q.data.product_count} icon={Package} testId="stat-products" />
            <StatCard label="Total stok" value={q.data.total_stock} icon={Boxes} testId="stat-stock" />
            <StatCard label="Masuk hari ini" value={q.data.in_today} icon={ArrowDownToLine}
              tone="bg-emerald-50 text-emerald-700" testId="stat-in" />
            <StatCard label="Keluar hari ini" value={q.data.out_today} icon={ArrowUpFromLine}
              tone="bg-sky-50 text-sky-700" testId="stat-out" />
            <StatCard label="Stok menipis" value={q.data.alert_count} icon={AlertTriangle}
              tone={q.data.alert_count ? "bg-amber-50 text-amber-700" : undefined} testId="stat-alert" />
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader><CardTitle>Masuk & keluar 7 hari terakhir</CardTitle></CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={q.data.last_7_days.map((d) => ({ ...d, label: fmtDayShort(d.date) }))}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} width={36} />
                    <Tooltip cursor={{ fill: "var(--muted)" }} />
                    <Legend />
                    <Bar dataKey="qty_in" name="Masuk" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="qty_out" name="Keluar" fill="var(--chart-2)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Stok menipis</CardTitle></CardHeader>
              <CardContent>
                {q.data.alerts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Semua stok di atas minimum. 👍</p>
                ) : (
                  <ul className="grid gap-2" data-testid="alert-list">
                    {q.data.alerts.slice(0, 8).map((a) => (
                      <li key={a.variant.id}>
                        <Link href={`/barang/${a.variant.product_id}`}
                          className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 hover:bg-muted">
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">{a.variant.product_name}</span>
                            <span className="text-xs text-muted-foreground">{variantLabel(a.variant)}</span>
                          </span>
                          <span className={cn("shrink-0 text-sm tabular-nums",
                            a.stock === 0 ? "font-semibold text-red-600" : "text-amber-700")}>
                            {a.stock} / min {a.min_stock}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader><CardTitle>10 transaksi terbaru</CardTitle></CardHeader>
            <CardContent>
              {q.data.recent.length === 0 ? (
                <EmptyState title="Belum ada transaksi" />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Waktu</TableHead>
                      <TableHead>Barang</TableHead>
                      <TableHead>Tipe</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="hidden md:table-cell">Petugas</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {q.data.recent.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell className="whitespace-nowrap tabular-nums">{fmtDateTime(m.created_at)}</TableCell>
                        <TableCell>
                          <span className="font-medium">{m.variant.product_name}</span>{" "}
                          <span className="text-muted-foreground">({variantLabel(m.variant)})</span>
                        </TableCell>
                        <TableCell><MovementTypeBadge movement={m} /></TableCell>
                        <TableCell className="text-right font-medium tabular-nums">
                          {m.qty > 0 ? `+${m.qty}` : m.qty}
                        </TableCell>
                        <TableCell className="hidden md:table-cell">{m.user.name}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
