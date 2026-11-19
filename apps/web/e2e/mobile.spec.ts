import { expect, test } from "@playwright/test";

import { loginAsAdmin } from "./support";

test("tampilan HP: bottom nav & menu samping bekerja, tanpa scroll horizontal", async ({ page }) => {
  await loginAsAdmin(page);
  const bottom = page.getByRole("navigation", { name: "Menu bawah" });
  await expect(bottom).toBeVisible();
  await bottom.getByRole("link", { name: "Barang" }).click();
  await expect(page).toHaveURL(/\/barang$/);

  await page.getByRole("button", { name: "Buka menu" }).click();
  await page.getByRole("dialog").getByRole("link", { name: "Akun Saya" }).click();
  await expect(page).toHaveURL(/\/akun$/);

  for (const path of ["/", "/barang", "/label", "/akun"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `scroll horizontal di ${path}`).toBeLessThanOrEqual(1);
  }
});
