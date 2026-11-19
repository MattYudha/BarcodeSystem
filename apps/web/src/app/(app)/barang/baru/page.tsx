"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NewCategoryDialog } from "@/components/app/category-dialog";
import { AdminOnly, PageHeader } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap, type Product, type Schemas } from "@/lib/api/client";
import { useCategories } from "@/lib/catalog";
import { todayWib } from "@/lib/format";

type Row = {
  key: number;
  size: string;
  color: string;
  min_stock: string;
  initial_stock: string;
  production_date: string;
  batch_code: string;
};

const SIZE_PRESETS = ["S", "M", "L", "XL", "XXL"];
let nextKey = 1;
const emptyRow = (size = ""): Row => ({
  key: nextKey++, size, color: "", min_stock: "5", initial_stock: "0", production_date: "", batch_code: "",
});

const toInt = (s: string) => (s.trim() === "" ? 0 : Number(s));

function NewProductForm() {
  const router = useRouter();
  const qc = useQueryClient();
  const categories = useCategories();
  const [categoryId, setCategoryId] = useState("");
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [description, setDescription] = useState("");
  const [rows, setRows] = useState<Row[]>([emptyRow()]);

  const update = (key: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const dupKeys = (() => {
    const seen = new Map<string, number>();
    const dups = new Set<number>();
    for (const r of rows) {
      const k = `${r.size.trim().toUpperCase()}|${r.color.trim().toLowerCase()}`;
      if (!r.size.trim()) continue;
      if (seen.has(k)) dups.add(r.key).add(seen.get(k)!);
      else seen.set(k, r.key);
    }
    return dups;
  })();

  const create = useMutation({
    mutationFn: () => {
      const body: Schemas["ProductCreateIn"] = {
        category_id: Number(categoryId),
        name,
        description: description || null,
        price: price ? Number(price.replace(/\D/g, "")) : null,
        variants: rows.map((r) => {
          const initial = toInt(r.initial_stock);
          return {
            size: r.size,
            color: r.color || null,
            min_stock: toInt(r.min_stock),
            initial_stock: initial,
            production_date: initial > 0 && r.production_date ? r.production_date : null,
            batch_code: initial > 0 && r.batch_code ? r.batch_code : null,
          };
        }),
      };
      return unwrap<Product>(api.POST("/api/v1/products", { body }));
    },
    onSuccess: async (p) => {
      await qc.invalidateQueries();
      toast.success(`Barang ${p.code} dibuat dengan ${p.variants.length} varian.`);
      router.push(`/barang/${p.id}?baru=1`);
    },
  });

  const canSubmit =
    categoryId && name.trim() && rows.every((r) => r.size.trim()) && dupKeys.size === 0 && !create.isPending;

  return (
    <form
      className="grid gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) create.mutate();
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle>Data barang</CardTitle>
          <CardDescription>Kode barang (BHV-xxxx) dibuat otomatis oleh sistem.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="name">Nama model *</Label>
            <Input id="name" required maxLength={150} placeholder="mis. Kemeja Batik Pria"
              value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label>Kategori *</Label>
            <div className="flex gap-2">
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger className="w-full" aria-label="Kategori">
                  <SelectValue placeholder="Pilih kategori" />
                </SelectTrigger>
                <SelectContent>
                  {categories.data?.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <NewCategoryDialog
                onCreated={(c) => setCategoryId(String(c.id))}
                trigger={<Button type="button" variant="outline" size="icon" aria-label="Kategori baru"><Plus /></Button>}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="price">Harga (opsional)</Label>
            <Input id="price" inputMode="numeric" placeholder="Rp"
              value={price ? Number(price).toLocaleString("id-ID") : ""}
              onChange={(e) => setPrice(e.target.value.replace(/\D/g, "").slice(0, 12))} />
          </div>
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="desc">Deskripsi (opsional)</Label>
            <Textarea id="desc" rows={2} maxLength={2000} value={description}
              onChange={(e) => setDescription(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>Varian ukuran & warna</CardTitle>
            <CardDescription>
              Setiap varian mendapat barcode sendiri. Stok awal dicatat sebagai transaksi masuk.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-1">
            {SIZE_PRESETS.map((s) => (
              <Button key={s} type="button" size="sm" variant="outline"
                onClick={() => setRows((rs) => [...rs.filter((r) => r.size.trim()), emptyRow(s)])}>
                + {s}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          {rows.map((r, i) => {
            const hasInitial = toInt(r.initial_stock) > 0;
            return (
              <div key={r.key} data-testid="variant-row"
                className="grid grid-cols-2 gap-2 rounded-lg border p-3 sm:grid-cols-6 lg:grid-cols-[1fr_1.4fr_0.8fr_0.8fr_1.2fr_1fr_auto]">
                <Field label="Ukuran *">
                  <Input aria-label={`Ukuran varian ${i + 1}`} required maxLength={20} placeholder="M / 32"
                    value={r.size} aria-invalid={dupKeys.has(r.key)}
                    onChange={(e) => update(r.key, { size: e.target.value.toUpperCase() })} />
                </Field>
                <Field label="Warna">
                  <Input aria-label={`Warna varian ${i + 1}`} maxLength={40} placeholder="opsional"
                    value={r.color} aria-invalid={dupKeys.has(r.key)}
                    onChange={(e) => update(r.key, { color: e.target.value })} />
                </Field>
                <Field label="Stok min">
                  <Input aria-label={`Stok minimum varian ${i + 1}`} type="number" min={0} value={r.min_stock}
                    onChange={(e) => update(r.key, { min_stock: e.target.value })} />
                </Field>
                <Field label="Stok awal">
                  <Input aria-label={`Stok awal varian ${i + 1}`} type="number" min={0} value={r.initial_stock}
                    onChange={(e) => update(r.key, { initial_stock: e.target.value })} />
                </Field>
                <Field label="Tgl produksi">
                  <Input aria-label={`Tanggal produksi varian ${i + 1}`} type="date" max={todayWib()}
                    disabled={!hasInitial} value={r.production_date}
                    onChange={(e) => update(r.key, { production_date: e.target.value })} />
                </Field>
                <Field label="Batch">
                  <Input aria-label={`Batch varian ${i + 1}`} maxLength={40} disabled={!hasInitial}
                    value={r.batch_code} onChange={(e) => update(r.key, { batch_code: e.target.value })} />
                </Field>
                <div className="flex items-end">
                  <Button type="button" variant="ghost" size="icon" aria-label={`Hapus varian ${i + 1}`}
                    disabled={rows.length === 1}
                    onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                    <Trash2 />
                  </Button>
                </div>
              </div>
            );
          })}
          {dupKeys.size > 0 && (
            <p className="text-sm text-destructive">Ada varian ganda (ukuran + warna sama).</p>
          )}
          <Button type="button" variant="outline" className="justify-self-start"
            onClick={() => setRows((rs) => [...rs, emptyRow()])}>
            <Plus /> Tambah varian
          </Button>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" asChild><Link href="/barang">Batal</Link></Button>
        <Button type="submit" size="lg" disabled={!canSubmit}>
          {create.isPending && <Loader2 className="animate-spin" />} Simpan barang
        </Button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

export default function NewProductPage() {
  return (
    <AdminOnly>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/barang"><ArrowLeft /> Daftar barang</Link>
      </Button>
      <PageHeader title="Tambah barang" />
      <NewProductForm />
    </AdminOnly>
  );
}
