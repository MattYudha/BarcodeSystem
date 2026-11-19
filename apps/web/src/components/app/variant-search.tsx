"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { useDebounced } from "@/hooks/use-debounced";
import { api, unwrap, type Schemas, type Variant } from "@/lib/api/client";
import { variantLabel } from "@/lib/format";

/** Cari varian (nama/kode/barcode) lalu pilih. */
export function VariantSearch({
  onPick,
  exclude,
  placeholder = "Cari barang / barcode…",
  archived = "active",
}: {
  onPick: (v: Variant) => void;
  exclude?: Set<number>;
  placeholder?: string;
  archived?: "active" | "all";
}) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const results = useQuery({
    queryKey: ["variants", { q: dq, archived, picker: true }],
    queryFn: () =>
      unwrap<Schemas["Page_VariantOut_"]>(
        api.GET("/api/v1/variants", { params: { query: { q: dq, page_size: 8, archived } } }),
      ),
    enabled: dq.length >= 2,
  });
  return (
    <div className="relative">
      <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
      <Input className="pl-8" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Cari varian" />
      {dq.length >= 2 && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border bg-popover shadow-md">
          {results.isPending ? (
            <p className="p-3 text-sm text-muted-foreground">Mencari…</p>
          ) : results.data?.items.length ? (
            results.data.items.map((v) => (
              <button key={v.id} type="button" disabled={exclude?.has(v.id)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50"
                onClick={() => { onPick(v); setQ(""); }}>
                <span className="min-w-0">
                  <span className="block truncate font-medium">{v.product_name}</span>
                  <span className="text-xs text-muted-foreground">{variantLabel(v)} · {v.barcode}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">stok {v.stock}</span>
              </button>
            ))
          ) : (
            <p className="p-3 text-sm text-muted-foreground">Tidak ditemukan.</p>
          )}
        </div>
      )}
    </div>
  );
}
