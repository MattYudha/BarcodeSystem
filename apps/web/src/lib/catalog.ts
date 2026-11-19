"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Category, type Product } from "@/lib/api/client";

export const catalogKeys = {
  categories: (all = false) => ["categories", { all }] as const,
  products: (params: object) => ["products", params] as const,
  product: (id: number) => ["product", id] as const,
  variants: (params: object) => ["variants", params] as const,
};

export function useCategories(includeArchived = false) {
  return useQuery({
    queryKey: catalogKeys.categories(includeArchived),
    queryFn: () =>
      unwrap<Category[]>(
        api.GET("/api/v1/categories", { params: { query: { include_archived: includeArchived } } }),
      ),
    staleTime: 60_000,
  });
}

export function useProduct(id: number) {
  return useQuery({
    queryKey: catalogKeys.product(id),
    queryFn: () =>
      unwrap<Product>(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: id } } })),
    enabled: Number.isFinite(id) && id > 0,
  });
}

/** Query key prefix yang perlu di-refresh setelah perubahan katalog/stok. */
export const CATALOG_INVALIDATE = [["products"], ["product"], ["variants"], ["categories"], ["dashboard"]];
