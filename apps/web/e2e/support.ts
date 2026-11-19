import { expect, request, type APIRequestContext, type Page } from "@playwright/test";

export const ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@bhavia-e2e.com",
  password: process.env.E2E_ADMIN_PASSWORD ?? "E2e-Admin-Pass1",
};

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export function uid(prefix = ""): string {
  return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** Klien API (lewat rewrite Next, sama seperti browser) yang sudah login. */
export async function apiAs(email: string, password: string): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: BASE });
  const r = await ctx.post("/api/v1/auth/login", { data: { email, password } });
  expect(r.status(), await r.text()).toBe(200);
  return ctx;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- payload tes fleksibel
export async function json<T = any>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  expect(res.ok(), `${res.status()} ${await res.text()}`).toBeTruthy();
  return (await res.json()) as T;
}

export async function createStaff(admin: APIRequestContext, opts: { password?: string } = {}) {
  const email = `${uid("staf-")}@bhavia-e2e.com`;
  const user = await json(
    await admin.post("/api/v1/users", {
      data: { name: `Staf ${uid()}`, email, role: "staff", ...(opts.password ? { password: opts.password } : {}) },
    }),
  );
  return { ...user, email, password: opts.password ?? user.temp_password };
}

export async function createCategory(admin: APIRequestContext) {
  return json(await admin.post("/api/v1/categories", { data: { name: uid("Kategori ") } }));
}

export async function createProduct(
  admin: APIRequestContext,
  variants = [
    { size: "M", min_stock: 5, initial_stock: 10 },
    { size: "L", min_stock: 5, initial_stock: 2 },
  ],
) {
  const cat = await createCategory(admin);
  return json(
    await admin.post("/api/v1/products", {
      data: { category_id: cat.id, name: uid("Kemeja E2E "), price: 150000, variants },
    }),
  );
}

/** Isi form login. `expectSuccess` (default) menunggu sampai keluar dari /login agar navigasi
 *  berikutnya tidak membatalkan request login yang sedang berjalan. */
export async function login(page: Page, email: string, password: string, expectSuccess = true) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Masuk" }).click();
  if (expectSuccess) await expect(page).not.toHaveURL(/\/login/);
}

export async function loginAsAdmin(page: Page) {
  await login(page, ADMIN.email, ADMIN.password);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}
