# Bhavia Inventory — Web (Next.js 16)

Frontend untuk API di `apps/api`. Browser memanggil `/api/*` di domain web; Next meneruskannya ke
`API_ORIGIN` (rewrite) sehingga cookie sesi first-party.

```bash
pnpm install
API_ORIGIN=http://localhost:8000 pnpm dev   # http://localhost:3000
pnpm gen:api      # regenerasi tipe dari OpenAPI FastAPI (wajib setelah API berubah; dicek CI)
pnpm lint && pnpm typecheck && pnpm build
pnpm e2e          # Playwright: butuh build + API jalan (lihat README root)
```

Catatan Next 16: `cacheComponents`/PPR aktif — komponen yang memakai `useSearchParams`/`usePathname`
di route dinamis harus berada di dalam `<Suspense>`. File `proxy.ts` (dulu `middleware`) menjaga
rute tanpa cookie sesi.
