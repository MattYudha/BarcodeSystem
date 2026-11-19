import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, createProduct, json, login, loginAsAdmin, uid } from "./support";

test.describe("Alur A: tambah barang, varian, barcode, label", () => {
  test("admin membuat barang + kategori baru + varian dengan stok awal", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/barang/baru");
    const name = uid("Gamis Brokat ");
    const category = uid("Gamis ");

    await page.getByLabel("Nama model *").fill(name);
    await page.getByRole("button", { name: "Kategori baru" }).click();
    await page.getByLabel("Nama kategori").fill(category);
    await page.getByRole("button", { name: "Simpan", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Kategori" })).toContainText(category);
    await page.getByLabel("Harga (opsional)").fill("375000");

    // baris pertama kosong diganti preset ukuran
    await page.getByRole("button", { name: "+ L" }).click();
    await page.getByRole("button", { name: "+ XL" }).click();
    await expect(page.getByTestId("variant-row")).toHaveCount(2);
    await page.getByLabel("Warna varian 1").fill("Hijau Botol");
    await page.getByLabel("Stok awal varian 1").fill("7");
    await page.getByLabel("Stok awal varian 2").fill("3");
    await page.getByLabel("Stok minimum varian 2").fill("5");

    // varian ganda ditolak sebelum dikirim
    await page.getByRole("button", { name: "+ L" }).click();
    await page.getByLabel("Warna varian 3").fill("hijau botol");
    await expect(page.getByText("Ada varian ganda")).toBeVisible();
    await expect(page.getByRole("button", { name: "Simpan barang" })).toBeDisabled();
    await page.getByRole("button", { name: "Hapus varian 3" }).click();

    await page.getByRole("button", { name: "Simpan barang" }).click();
    await expect(page.getByText("Barang tersimpan.")).toBeVisible();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByTestId("total-stock")).toHaveText("10");

    const rows = page.getByTestId("variant");
    await expect(rows).toHaveCount(2);
    const barcodes = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-barcode")));
    expect(barcodes[0]).toMatch(/^BHV-\d{4,}-01$/);
    expect(barcodes[1]).toBe(barcodes[0]!.replace(/-01$/, "-02"));
    await expect(rows.nth(1)).toContainText("Menipis");

    // gambar barcode SVG termuat dari API (cookie sesi first-party)
    const img = rows.first().getByRole("img");
    await expect(img).toHaveJSProperty("complete", true);
    expect(await img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(50);
  });

  test("ubah nama tidak mengubah barcode; ukuran varian terkunci setelah ada transaksi", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    await loginAsAdmin(page);
    await page.goto(`/barang/${p.id}`);

    await page.getByRole("button", { name: "Ubah" }).click();
    const newName = uid("Nama Baru ");
    await page.getByLabel("Nama model").fill(newName);
    await page.getByRole("button", { name: "Simpan" }).click();
    await expect(page.getByRole("heading", { name: newName })).toBeVisible();
    await expect(page.getByTestId("variant").first()).toHaveAttribute("data-barcode", p.variants[0].barcode);

    await page.getByRole("button", { name: `Aksi varian ${p.variants[0].barcode}` }).click();
    await page.getByRole("menuitem", { name: "Ubah" }).click();
    await expect(page.getByLabel("Ukuran")).toBeDisabled();
    await expect(page.getByText("Ukuran & warna terkunci")).toBeVisible();
    await page.getByLabel("Stok minimum").fill("20");
    await page.getByRole("button", { name: "Simpan" }).click();
    await expect(page.getByTestId("variant").first()).toContainText("Menipis");
  });

  test("arsip, pulihkan, dan hapus permanen hanya tanpa transaksi", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const withStock = await createProduct(admin);
    const empty = await createProduct(admin, [{ size: "M", min_stock: 0, initial_stock: 0 }]);
    await loginAsAdmin(page);

    await page.goto(`/barang/${withStock.id}`);
    await expect(page.getByRole("button", { name: "Hapus" })).toHaveCount(0);
    await page.getByRole("button", { name: "Arsipkan" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Arsipkan" }).click();
    await expect(page.getByText(/Diarsipkan \d{2}\/\d{2}\/\d{4}/)).toBeVisible();
    const lookup = await admin.get(`/api/v1/variants/lookup?barcode=${withStock.variants[0].barcode}`);
    expect(lookup.status()).toBe(409);
    await page.getByRole("button", { name: "Pulihkan" }).click();
    await expect(page.getByRole("button", { name: "Arsipkan" })).toBeVisible();

    await page.goto(`/barang/${empty.id}`);
    await page.getByRole("button", { name: "Hapus" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Hapus" }).click();
    await expect(page).toHaveURL(/\/barang$/);
    expect((await admin.get(`/api/v1/products/${empty.id}`)).status()).toBe(404);
  });

  test("cari & filter daftar barang, filter dari URL", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    await loginAsAdmin(page);
    await page.goto("/barang");
    await page.getByLabel("Cari barang").fill(p.code);
    await expect(page).toHaveURL(new RegExp(`q=${p.code}`));
    await expect(page.getByRole("row")).toHaveCount(2); // header + 1
    await expect(page.getByRole("link", { name: p.name })).toBeVisible();

    await page.goto(`/barang?q=${encodeURIComponent(p.code)}&stock_status=alert`);
    await expect(page.getByRole("link", { name: p.name })).toBeVisible(); // L: 2 <= min 5
    await page.goto(`/barang?q=${encodeURIComponent(p.code)}&stock_status=out`);
    await expect(page.getByText("Tidak ada barang")).toBeVisible();
  });
});

test.describe("F-08 cetak label", () => {
  test("label dari detail barang: jumlah = stok, PDF dibuat & dipratinjau", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    await loginAsAdmin(page);
    await page.goto(`/barang/${p.id}`);
    await page.getByRole("main").getByRole("link", { name: "Cetak label", exact: true }).first().click();
    await expect(page).toHaveURL(/\/label\?items=/);

    const items = page.getByTestId("label-items").locator("li");
    await expect(items).toHaveCount(2);
    await expect(page.getByLabel(`Jumlah label ${p.variants[0].barcode}`)).toHaveValue("10");
    await expect(page.getByLabel(`Jumlah label ${p.variants[1].barcode}`)).toHaveValue("2");
    await expect(page.getByText(/12\s*label/)).toBeVisible();

    await page.getByRole("combobox", { name: "Template label" }).click();
    await page.getByRole("option", { name: /thermal 50×30/i }).click();
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/v1/labels/pdf")),
      page.getByRole("button", { name: "Buat PDF label" }).click(),
    ]);
    expect(resp.status()).toBe(200);
    expect(resp.headers()["content-type"]).toBe("application/pdf");
    const pdf = await resp.body();
    expect(pdf.subarray(0, 4).toString()).toBe("%PDF");
    expect((pdf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) ?? []).length).toBe(12);
    await expect(page.getByRole("dialog", { name: "Pratinjau label" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Unduh PDF" })).toHaveAttribute("download", /label-.*\.pdf/);
  });

  test("staf boleh cetak ulang label; tambah varian lewat pencarian", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const staffPw = "Rahasia-123";
    const staff = await json(await admin.post("/api/v1/users", {
      data: { name: "Staf Label", email: `${uid("lbl-")}@bhavia-e2e.com`, password: staffPw },
    }));
    await login(page, staff.email, staffPw);
    await page.goto("/label");
    await page.getByLabel("Cari varian").fill(p.variants[1].barcode);
    await page.getByRole("button", { name: new RegExp(p.name) }).click();
    await expect(page.getByLabel(`Jumlah label ${p.variants[1].barcode}`)).toHaveValue("2");
    await page.getByLabel(`Jumlah label ${p.variants[1].barcode}`).fill("5");
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/v1/labels/pdf")),
      page.getByRole("button", { name: "Buat PDF label" }).click(),
    ]);
    expect(resp.status()).toBe(200);
  });
});
