"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { EmptyState, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounced } from "@/hooks/use-debounced";
import { api, unwrap, type Product, type Schemas } from "@/lib/api/client";
import { catalogKeys, useCategories } from "@/lib/catalog";
import { num, rupiah } from "@/lib/format";
import { useIsAdmin } from "@/lib/session";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;
const ALL = "all";
type StockFilter = "ok" | "low" | "out" | "alert";

function VariantChips({ product }: { product: Product }) {
  return (
    <div className="flex flex-wrap gap-1">
      {product.variants.filter((v) => !v.is_archived || product.archived_at).map((v) => (
        <span
          key={v.id}
          title={`${v.barcode} · stok ${v.stock} (min ${v.min_stock})`}
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs tabular-nums",
            v.stock_status === "out" && "border-red-200 bg-red-50 text-red-700",
            v.stock_status === "low" && "border-amber-200 bg-amber-50 text-amber-800",
          )}
        >
          <b className="font-semibold">{v.size}</b>
          {v.color && <span className="max-w-20 truncate text-muted-foreground">{v.color}</span>}
          <span>{v.stock}</span>
        </span>
      ))}
    </div>
  );
}

function ProductList() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const isAdmin = useIsAdmin();
  const categories = useCategories();

  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounced(q);
  const category = params.get("category_id") ?? ALL;
  const status = (params.get("stock_status") ?? ALL) as StockFilter | typeof ALL;
  const archived = (params.get("archived") ?? "active") as "active" | "archived" | "all";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);

  function setParam(updates: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v == null || v === "" || v === ALL) next.delete(k);
      else next.set(k, v);
    }
    if (!("page" in updates)) next.delete("page");
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  }

  // sinkronkan kotak pencarian (debounced) ke URL
  useEffect(() => {
    if ((params.get("q") ?? "") !== debouncedQ) setParam({ q: debouncedQ || null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const query = {
    q: params.get("q") || undefined,
    category_id: category === ALL ? undefined : Number(category),
    stock_status: status === ALL ? undefined : status,
    archived,
    page,
    page_size: PAGE_SIZE,
  };
  const products = useQuery({
    queryKey: catalogKeys.products(query),
    queryFn: () =>
      unwrap<Schemas["Page_ProductOut_"]>(api.GET("/api/v1/products", { params: { query } })),
    placeholderData: keepPreviousData,
  });
  const totalPages = products.data ? Math.max(1, Math.ceil(products.data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <PageHeader
        title="Barang"
        description="Model barang beserta varian ukuran/warna dan stoknya."
        actions={
          isAdmin && (
            <Button asChild>
              <Link href="/barang/baru">
                <Plus /> Tambah barang
              </Link>
            </Button>
          )
        }
      />

      <Card className="mb-4 grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Cari nama, kode, atau barcode…"
            className="pl-8"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Cari barang"
          />
        </div>
        <Select value={category} onValueChange={(v) => setParam({ category_id: v })}>
          <SelectTrigger aria-label="Filter kategori" className="w-full">
            <SelectValue placeholder="Kategori" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Semua kategori</SelectItem>
            {categories.data?.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={(v) => setParam({ stock_status: v })}>
          <SelectTrigger aria-label="Filter status stok" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Semua status stok</SelectItem>
            <SelectItem value="alert">Perlu restock (≤ minimum)</SelectItem>
            <SelectItem value="low">Menipis</SelectItem>
            <SelectItem value="out">Habis</SelectItem>
            <SelectItem value="ok">Aman</SelectItem>
          </SelectContent>
        </Select>
        <Select value={archived} onValueChange={(v) => setParam({ archived: v === "active" ? null : v })}>
          <SelectTrigger aria-label="Filter arsip" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Barang aktif</SelectItem>
            <SelectItem value="archived">Diarsipkan</SelectItem>
            <SelectItem value="all">Semua</SelectItem>
          </SelectContent>
        </Select>
      </Card>

      {products.isPending ? (
        <LoadingBlock />
      ) : products.isError ? (
        <ErrorBlock error={products.error} onRetry={() => products.refetch()} />
      ) : products.data.items.length === 0 ? (
        <EmptyState
          title="Tidak ada barang"
          description={params.size ? "Coba ubah pencarian atau filter." : "Belum ada barang terdaftar."}
          action={isAdmin && !params.size && (
            <Button asChild><Link href="/barang/baru"><Plus /> Tambah barang pertama</Link></Button>
          )}
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-28">Kode</TableHead>
                <TableHead>Barang</TableHead>
                <TableHead className="hidden md:table-cell">Varian (ukuran · stok)</TableHead>
                <TableHead className="text-right">Total stok</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Harga</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {products.data.items.map((p) => (
                <TableRow key={p.id} className="cursor-pointer" onClick={() => router.push(`/barang/${p.id}`)}>
                  <TableCell className="font-mono text-xs">{p.code}</TableCell>
                  <TableCell>
                    <Link href={`/barang/${p.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                      {p.name}
                    </Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      {p.category.name} · {p.variant_count} varian
                      {p.alert_count > 0 && (
                        <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">
                          {p.alert_count} perlu restock
                        </Badge>
                      )}
                      {p.archived_at && <Badge variant="secondary">Diarsipkan</Badge>}
                    </div>
                    <div className="mt-2 md:hidden"><VariantChips product={p} /></div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell"><VariantChips product={p} /></TableCell>
                  <TableCell className="text-right font-semibold tabular-nums">{num(p.total_stock)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums sm:table-cell">{rupiah(p.price)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between border-t px-4 py-2 text-sm text-muted-foreground">
            <span>{num(products.data.total)} barang</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon-sm" aria-label="Halaman sebelumnya" disabled={page <= 1}
                onClick={() => setParam({ page: String(page - 1) })}><ChevronLeft /></Button>
              <span className="tabular-nums">{page} / {totalPages}</span>
              <Button variant="outline" size="icon-sm" aria-label="Halaman berikutnya" disabled={page >= totalPages}
                onClick={() => setParam({ page: String(page + 1) })}><ChevronRight /></Button>
            </div>
          </div>
        </Card>
      )}
    </>
  );
}

export default function BarangPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ProductList />
    </Suspense>
  );
}
