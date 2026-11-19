"use client";

import { MovementTypeBadge, reasonLabel } from "@/components/app/movement";
import { ReverseButton } from "@/components/app/reverse-dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Movement } from "@/lib/api/client";
import { fmtDate, fmtDateTime, variantLabel } from "@/lib/format";

/** Tabel transaksi bersama (kartu stok & laporan). */
export function MovementTable({
  movements,
  showProduct = true,
  showBalance = true,
}: {
  movements: Movement[];
  showProduct?: boolean;
  showBalance?: boolean;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-36">Waktu (WIB)</TableHead>
          {showProduct && <TableHead>Barang</TableHead>}
          <TableHead>Tipe</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          {showBalance && <TableHead className="text-right">Saldo</TableHead>}
          <TableHead className="hidden lg:table-cell">Keterangan</TableHead>
          <TableHead className="hidden md:table-cell">Petugas</TableHead>
          <TableHead className="w-28 print:hidden" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {movements.map((m) => {
          const info = [
            reasonLabel(m.reason),
            m.production_date && `Produksi ${fmtDate(m.production_date)}`,
            m.batch_code && `Batch ${m.batch_code}`,
            m.reversal_of && `Membatalkan #${m.reversal_of}`,
            m.note,
          ].filter(Boolean);
          return (
            <TableRow key={m.id} data-testid="movement-row" className={m.reversed_by ? "text-muted-foreground" : undefined}>
              <TableCell className="whitespace-nowrap tabular-nums">
                {fmtDateTime(m.created_at)}
                <span className="block text-xs text-muted-foreground">#{m.id}</span>
              </TableCell>
              {showProduct && (
                <TableCell>
                  <span className="font-medium">{m.variant.product_name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {variantLabel(m.variant)} · <span className="font-mono">{m.variant.barcode}</span>
                  </span>
                </TableCell>
              )}
              <TableCell><MovementTypeBadge movement={m} /></TableCell>
              <TableCell className="text-right font-semibold tabular-nums">{m.qty > 0 ? `+${m.qty}` : m.qty}</TableCell>
              {showBalance && <TableCell className="text-right tabular-nums">{m.balance_after}</TableCell>}
              <TableCell className="hidden max-w-64 text-sm lg:table-cell">{info.join(" · ") || "-"}</TableCell>
              <TableCell className="hidden text-sm md:table-cell">
                {m.user.name}
                {m.device_label && <span className="block text-xs text-muted-foreground">{m.device_label}</span>}
              </TableCell>
              <TableCell className="print:hidden"><ReverseButton movement={m} size="xs" /></TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
