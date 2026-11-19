"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap, type Product, type Variant } from "@/lib/api/client";
import { useCategories } from "@/lib/catalog";
import { todayWib } from "@/lib/format";

function useRefreshCatalog() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function EditProductDialog({ product, trigger }: { product: Product; trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const categories = useCategories(true);
  const refresh = useRefreshCatalog();
  const [name, setName] = useState(product.name);
  const [categoryId, setCategoryId] = useState(String(product.category.id));
  const [price, setPrice] = useState(product.price == null ? "" : String(product.price));
  const [description, setDescription] = useState(product.description ?? "");

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/products/{product_id}", {
          params: { path: { product_id: product.id } },
          body: {
            name,
            category_id: Number(categoryId),
            price: price ? Number(price) : null,
            description: description || null,
          },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      toast.success("Perubahan disimpan. Barcode tidak berubah.");
      setOpen(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <DialogHeader>
            <DialogTitle>Ubah barang {product.code}</DialogTitle>
            <DialogDescription>Kode barang & barcode tidak ikut berubah.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="e-name">Nama model</Label>
            <Input id="e-name" required maxLength={150} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label>Kategori</Label>
            <Select value={categoryId} onValueChange={setCategoryId}>
              <SelectTrigger className="w-full" aria-label="Kategori"><SelectValue /></SelectTrigger>
              <SelectContent>
                {categories.data?.filter((c) => !c.archived_at || String(c.id) === categoryId).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="e-price">Harga</Label>
            <Input id="e-price" inputMode="numeric" placeholder="kosongkan jika tidak ada"
              value={price ? Number(price).toLocaleString("id-ID") : ""}
              onChange={(e) => setPrice(e.target.value.replace(/\D/g, "").slice(0, 12))} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="e-desc">Deskripsi</Label>
            <Textarea id="e-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={save.isPending || !name.trim()}>
              {save.isPending && <Loader2 className="animate-spin" />} Simpan
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AddVariantDialog({ product, trigger }: { product: Product; trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const refresh = useRefreshCatalog();
  const [size, setSize] = useState("");
  const [color, setColor] = useState("");
  const [minStock, setMinStock] = useState("5");
  const [initial, setInitial] = useState("0");
  const [productionDate, setProductionDate] = useState("");
  const [batch, setBatch] = useState("");
  const hasInitial = Number(initial) > 0;

  const save = useMutation({
    mutationFn: () =>
      unwrap<Variant>(
        api.POST("/api/v1/products/{product_id}/variants", {
          params: { path: { product_id: product.id } },
          body: {
            size,
            color: color || null,
            min_stock: Number(minStock || 0),
            initial_stock: Number(initial || 0),
            production_date: hasInitial && productionDate ? productionDate : null,
            batch_code: hasInitial && batch ? batch : null,
          },
        }),
      ),
    onSuccess: async (v) => {
      await refresh();
      toast.success(`Varian ${v.size} dibuat dengan barcode ${v.barcode}`);
      setSize(""); setColor(""); setInitial("0"); setProductionDate(""); setBatch("");
      setOpen(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <DialogHeader>
            <DialogTitle>Tambah varian</DialogTitle>
            <DialogDescription>Barcode dibuat otomatis untuk varian baru.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="v-size">Ukuran *</Label>
              <Input id="v-size" required maxLength={20} value={size} onChange={(e) => setSize(e.target.value.toUpperCase())} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-color">Warna</Label>
              <Input id="v-color" maxLength={40} value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-min">Stok minimum</Label>
              <Input id="v-min" type="number" min={0} value={minStock} onChange={(e) => setMinStock(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-init">Stok awal</Label>
              <Input id="v-init" type="number" min={0} value={initial} onChange={(e) => setInitial(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-date">Tgl produksi</Label>
              <Input id="v-date" type="date" max={todayWib()} disabled={!hasInitial}
                value={productionDate} onChange={(e) => setProductionDate(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-batch">Batch</Label>
              <Input id="v-batch" maxLength={40} disabled={!hasInitial} value={batch} onChange={(e) => setBatch(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={save.isPending || !size.trim()}>
              {save.isPending && <Loader2 className="animate-spin" />} Simpan varian
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EditVariantDialog({ variant, trigger }: { variant: Variant; trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const refresh = useRefreshCatalog();
  const [size, setSize] = useState(variant.size);
  const [color, setColor] = useState(variant.color ?? "");
  const [minStock, setMinStock] = useState(String(variant.min_stock));
  const locked = variant.has_movements;

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/variants/{variant_id}", {
          params: { path: { variant_id: variant.id } },
          body: locked
            ? { min_stock: Number(minStock || 0) }
            : { size, color: color || null, min_stock: Number(minStock || 0) },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      toast.success("Varian diperbarui");
      setOpen(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <DialogHeader>
            <DialogTitle>Ubah varian</DialogTitle>
            <DialogDescription className="font-mono">{variant.barcode}</DialogDescription>
          </DialogHeader>
          {locked && (
            <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              Ukuran & warna terkunci karena varian sudah punya transaksi (label yang sudah tercetak
              akan jadi salah). Buat varian baru bila perlu.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="ev-size">Ukuran</Label>
              <Input id="ev-size" disabled={locked} required value={size} onChange={(e) => setSize(e.target.value.toUpperCase())} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ev-color">Warna</Label>
              <Input id="ev-color" disabled={locked} value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ev-min">Stok minimum</Label>
            <Input id="ev-min" type="number" min={0} value={minStock} onChange={(e) => setMinStock(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />} Simpan
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
