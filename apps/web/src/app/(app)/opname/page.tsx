"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AdminOnly, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/format";

import { OpnameDetail, OpnameStatusBadge } from "./opname-detail";

function OpnameHome() {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const list = useQuery({
    queryKey: ["opnames"],
    queryFn: () => unwrap<Schemas["OpnameOut"][]>(api.GET("/api/v1/opnames", { params: { query: { limit: 30 } } })),
  });
  const start = useMutation({
    mutationFn: () => unwrap<Schemas["OpnameOut"]>(api.POST("/api/v1/opnames", { body: { note: note || null } })),
    onSuccess: async () => { setNote(""); await qc.invalidateQueries({ queryKey: ["opnames"] }); },
  });

  if (list.isPending) return <LoadingBlock />;
  if (list.isError) return <ErrorBlock error={list.error} onRetry={() => list.refetch()} />;
  const draft = list.data.find((o) => o.status === "draft");
  const history = list.data.filter((o) => o.status !== "draft");

  return (
    <div className="grid gap-6">
      {draft ? (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Opname berjalan: {draft.code}</h2>
          <OpnameDetail id={draft.id} />
        </section>
      ) : (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ClipboardCheck className="size-5" /> Mulai stock opname</CardTitle>
            <CardDescription>
              Hitung fisik barang di gudang. Saat selesai, selisih dengan stok sistem dicatat otomatis sebagai penyesuaian.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); start.mutate(); }}>
              <Input placeholder="Catatan (opsional), mis. Opname akhir bulan" maxLength={500} value={note}
                onChange={(e) => setNote(e.target.value)} aria-label="Catatan opname" />
              <Button type="submit" disabled={start.isPending}>
                {start.isPending && <Loader2 className="animate-spin" />} Mulai
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {history.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Riwayat</h2>
          <Card className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Kode</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Dimulai</TableHead>
                  <TableHead className="hidden sm:table-cell">Selesai</TableHead>
                  <TableHead className="text-right">Varian</TableHead>
                  <TableHead className="hidden md:table-cell">Catatan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="pl-6"><Link href={`/opname/${o.id}`} className="font-mono font-medium hover:underline">{o.code}</Link></TableCell>
                    <TableCell><OpnameStatusBadge status={o.status} /></TableCell>
                    <TableCell className="whitespace-nowrap">{fmtDateTime(o.created_at)}</TableCell>
                    <TableCell className="hidden whitespace-nowrap sm:table-cell">{fmtDateTime(o.finalized_at ?? o.cancelled_at)}</TableCell>
                    <TableCell className="text-right tabular-nums">{o.item_count}</TableCell>
                    <TableCell className="hidden max-w-64 truncate md:table-cell">{o.note ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </section>
      )}
    </div>
  );
}

export default function OpnamePage() {
  return (
    <AdminOnly>
      <PageHeader title="Stock Opname" description="Penyesuaian stok berdasarkan hitungan fisik." />
      <OpnameHome />
    </AdminOnly>
  );
}
