"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  ArrowLeft,
  CheckCircle2,
  History,
  MoreHorizontal,
  Pencil,
  Plus,
  Tags,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { toast } from "sonner";

import { ErrorBlock, LoadingBlock, PageHeader, StockBadge } from "@/components/app/common";
import { Confirm } from "@/components/app/confirm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, unwrap, type Product } from "@/lib/api/client";
import { useProduct } from "@/lib/catalog";
import { fmtDateTime, num, rupiah } from "@/lib/format";
import { useIsAdmin } from "@/lib/session";

import { AddVariantDialog, EditProductDialog, EditVariantDialog } from "./dialogs";

function labelHref(p: Product, variantIds?: number[]) {
  const vs = p.variants.filter((v) => !v.is_archived && (!variantIds || variantIds.includes(v.id)));
  // salinan default = stok saat ini (1 label per barang fisik), minimal 1
  const items = vs.map((v) => `${v.id}:${Math.max(1, v.stock)}`).join(",");
  return `/label?items=${items}`;
}

function ProductDetail() {
  const { id } = useParams<{ id: string }>();
  const justCreated = useSearchParams().get("baru") === "1";
  const product = useProduct(Number(id));
  const isAdmin = useIsAdmin();
  const qc = useQueryClient();
  const router = useRouter();

  if (product.isPending) return <LoadingBlock />;
  if (product.isError) return <ErrorBlock error={product.error} onRetry={() => product.refetch()} />;
  const p = product.data;
  const refresh = () => qc.invalidateQueries();

  const archive = (on: boolean) =>
    unwrap(
      api.POST(on ? "/api/v1/products/{product_id}/archive" : "/api/v1/products/{product_id}/unarchive", {
        params: { path: { product_id: p.id } },
      }),
    ).then(async () => {
      await refresh();
      toast.success(on ? "Barang diarsipkan dan tidak bisa di-scan lagi." : "Barang dipulihkan.");
    });

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/barang"><ArrowLeft /> Daftar barang</Link>
      </Button>

      {justCreated && (
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900 sm:flex-row sm:items-center">
          <CheckCircle2 className="size-5 shrink-0" />
          <p className="flex-1 text-sm">
            Barang tersimpan. Langkah berikutnya: cetak label barcode lalu tempel di setiap barang.
          </p>
          <Button asChild size="sm"><Link href={labelHref(p)}><Tags /> Cetak label</Link></Button>
        </div>
      )}

      <PageHeader
        title={p.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{p.code}</span>·<span>{p.category.name}</span>·
            <span>{rupiah(p.price)}</span>
            {p.archived_at && <Badge variant="secondary">Diarsipkan {fmtDateTime(p.archived_at)}</Badge>}
          </span>
        }
        actions={
          <>
            <Button variant="outline" asChild><Link href={labelHref(p)}><Tags /> Cetak label</Link></Button>
            {isAdmin && (
              <>
                <EditProductDialog key={p.updated_at} product={p} trigger={<Button variant="outline"><Pencil /> Ubah</Button>} />
                {p.archived_at ? (
                  <Button variant="outline" onClick={() => archive(false)}><ArchiveRestore /> Pulihkan</Button>
                ) : (
                  <Confirm
                    title="Arsipkan barang?"
                    description="Barang arsip tidak muncul di scan dan daftar aktif. Riwayat transaksi tetap tersimpan dan barang bisa dipulihkan kapan saja."
                    confirmLabel="Arsipkan"
                    onConfirm={() => archive(true)}
                    trigger={<Button variant="outline"><Archive /> Arsipkan</Button>}
                  />
                )}
                {!p.has_movements && (
                  <Confirm
                    destructive
                    title="Hapus permanen?"
                    description="Barang ini belum punya transaksi sehingga boleh dihapus permanen (untuk salah input)."
                    confirmLabel="Hapus"
                    onConfirm={() =>
                      unwrap(api.DELETE("/api/v1/products/{product_id}", { params: { path: { product_id: p.id } } }))
                        .then(() => { toast.success("Barang dihapus"); router.replace("/barang"); return refresh(); })
                    }
                    trigger={<Button variant="destructive"><Trash2 /> Hapus</Button>}
                  />
                )}
              </>
            )}
          </>
        }
      />

      <div className="mb-4 grid grid-cols-3 gap-3">
        <Card className="py-3"><CardContent className="px-4">
          <p className="text-xs text-muted-foreground">Total stok</p>
          <p className="text-xl font-semibold tabular-nums" data-testid="total-stock">{num(p.total_stock)}</p>
        </CardContent></Card>
        <Card className="py-3"><CardContent className="px-4">
          <p className="text-xs text-muted-foreground">Varian aktif</p>
          <p className="text-xl font-semibold tabular-nums">{p.variant_count}</p>
        </CardContent></Card>
        <Card className="py-3"><CardContent className="px-4">
          <p className="text-xs text-muted-foreground">Perlu restock</p>
          <p className="text-xl font-semibold tabular-nums">{p.alert_count}</p>
        </CardContent></Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Varian & barcode</CardTitle>
          {isAdmin && !p.archived_at && (
            <AddVariantDialog product={p} trigger={<Button size="sm"><Plus /> Tambah varian</Button>} />
          )}
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Barcode</TableHead>
                <TableHead>Ukuran</TableHead>
                <TableHead>Warna</TableHead>
                <TableHead className="text-right">Stok</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Min</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10 pr-6" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {p.variants.map((v) => (
                <TableRow key={v.id} data-testid="variant" data-barcode={v.barcode}
                  className={v.is_archived ? "opacity-60" : undefined}>
                  <TableCell className="pl-6">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/api/v1/variants/${v.id}/barcode.svg`} alt={`Barcode ${v.barcode}`}
                      className="hidden h-10 w-auto sm:block" loading="lazy" />
                    <span className="font-mono text-xs sm:hidden">{v.barcode}</span>
                  </TableCell>
                  <TableCell className="font-semibold">{v.size}</TableCell>
                  <TableCell>{v.color ?? <span className="text-muted-foreground">-</span>}</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums">{num(v.stock)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums sm:table-cell">{v.min_stock}</TableCell>
                  <TableCell>
                    {v.is_archived ? <Badge variant="secondary">Arsip</Badge> : <StockBadge status={v.stock_status} />}
                  </TableCell>
                  <TableCell className="pr-6">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Aksi varian ${v.barcode}`}>
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem asChild>
                          <Link href={`/barang/${p.id}/kartu/${v.id}`}><History /> Kartu stok</Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                          <Link href={`/label?items=${v.id}:${Math.max(1, v.stock)}`}><Tags /> Cetak label</Link>
                        </DropdownMenuItem>
                        {isAdmin && (
                          <>
                            <EditVariantDialog key={`${v.id}-${v.size}-${v.color}-${v.min_stock}`} variant={v} trigger={
                              <DropdownMenuItem onSelect={(e) => e.preventDefault()}><Pencil /> Ubah</DropdownMenuItem>
                            } />
                            <DropdownMenuSeparator />
                            {!p.archived_at && (
                              <DropdownMenuItem
                                onSelect={() =>
                                  unwrap(api.POST(v.is_archived ? "/api/v1/variants/{variant_id}/unarchive"
                                    : "/api/v1/variants/{variant_id}/archive", { params: { path: { variant_id: v.id } } }))
                                    .then(refresh)
                                    .then(() => toast.success(v.is_archived ? "Varian dipulihkan" : "Varian diarsipkan"))
                                    .catch((e: Error) => toast.error(e.message))
                                }
                              >
                                {v.is_archived ? <><ArchiveRestore /> Pulihkan</> : <><Archive /> Arsipkan</>}
                              </DropdownMenuItem>
                            )}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}

export default function ProductDetailPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ProductDetail />
    </Suspense>
  );
}
