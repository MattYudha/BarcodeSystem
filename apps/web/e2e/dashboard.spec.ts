import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, createProduct, json, loginAsAdmin } from "./support";

test("F-03/F-04 dashboard menampilkan ringkasan yang sama dengan API", async ({ page }) => {
  const admin = await apiAs(ADMIN.email, ADMIN.password);
  const p = await createProduct(admin);
  const dash = await json(await admin.get("/api/v1/dashboard"));

  await loginAsAdmin(page);
  await expect(page.getByTestId("stat-products")).toHaveText(dash.product_count.toLocaleString("id-ID"));
  await expect(page.getByTestId("stat-in")).toHaveText(dash.in_today.toLocaleString("id-ID"));
  await expect(page.getByTestId("stat-alert")).toHaveText(dash.alert_count.toLocaleString("id-ID"));
  await expect(page.getByRole("cell", { name: new RegExp(p.name) }).first()).toBeVisible();
  // link peringatan menuju daftar barang terfilter
  await page.getByRole("link", { name: /stoknya menipis/ }).click();
  await expect(page).toHaveURL(/\/barang\?stock_status=alert/);
});
