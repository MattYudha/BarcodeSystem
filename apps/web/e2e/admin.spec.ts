import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, createProduct, createStaff, json, login, loginAsAdmin, uid } from "./support";

async function cancelDraftOpnames() {
  const admin = await apiAs(ADMIN.email, ADMIN.password);
  for (const o of await json(await admin.get("/api/v1/opnames?status=draft"))) {
    await admin.post(`/api/v1/opnames/${o.id}/cancel`);
  }
}

test.describe("F-13 stock opname", () => {
  test.beforeEach(cancelDraftOpnames);

  test("hitung via scan & ketik, selesaikan -> stok = hitungan fisik", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin); // M=10, L=2
    const [m, l] = p.variants;
    await loginAsAdmin(page);
    await page.goto("/opname");
    await page.getByLabel("Catatan opname").fill("Opname E2E");
    await page.getByRole("button", { name: "Mulai" }).click();
    await expect(page.getByRole("heading", { name: /Opname berjalan: SO-/ })).toBeVisible();

    for (let i = 0; i < 3; i++) {
      await page.getByLabel("Barcode opname").fill(l.barcode);
      await page.getByLabel("Barcode opname").press("Enter");
      await expect(page.getByTestId("opname-last")).toContainText(`dihitung ${i + 1}`);
    }
    await page.getByLabel("Barcode opname").fill(m.barcode);
    await page.getByLabel("Barcode opname").press("Enter");
    await expect(page.getByTestId("opname-item")).toHaveCount(2);
    const mCount = page.getByLabel(`Jumlah fisik ${m.barcode}`);
    await mCount.fill("8");
    await mCount.press("Enter");
    const mRow = page.locator(`[data-testid=opname-item][data-barcode="${m.barcode}"]`);
    await expect(mRow.getByTestId("opname-diff")).toHaveText("-2");
    await expect(page.locator(`[data-testid=opname-item][data-barcode="${l.barcode}"]`).getByTestId("opname-diff")).toHaveText("+1");

    await page.getByLabel("Barcode opname").fill("BHV-0000-99");
    await page.getByLabel("Barcode opname").press("Enter");
    await expect(page.getByTestId("opname-last")).toContainText("Barcode tidak dikenal");

    await page.getByRole("button", { name: "Selesaikan opname" }).click();
    await expect(page.getByRole("alertdialog")).toContainText("2 varian akan disesuaikan");
    await page.getByRole("alertdialog").getByRole("button", { name: "Selesaikan" }).click();
    await expect(page.getByText(/Stock opname SO-\d+ selesai/)).toBeVisible();

    const stock = async (id: number) => (await json(await admin.get(`/api/v1/variants/${id}`))).stock;
    expect(await stock(m.id)).toBe(8);
    expect(await stock(l.id)).toBe(3);
    await expect(page.getByRole("button", { name: "Mulai" })).toBeVisible(); // siap opname berikutnya
    await expect(page.getByRole("link", { name: /^SO-/ }).first()).toBeVisible();
  });
});

test.describe("F-15 laporan", () => {
  test("ringkasan harian, filter tipe, unduh CSV", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const m = p.variants[0];
    await admin.post("/api/v1/movements", {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: { type: "OUT", lines: [{ variant_id: m.id, qty: 3, reason: "sale" }] },
    });
    await loginAsAdmin(page);
    await page.goto("/laporan");
    const row = page.locator(`[data-testid=report-row][data-barcode="${m.barcode}"]`);
    await expect(row).toBeVisible();
    await expect(row.getByRole("cell")).toHaveText([new RegExp(p.name), "0", "10", "3", "0", "0", "7"]);

    await page.getByRole("tab", { name: "Daftar transaksi" }).click();
    await page.getByRole("combobox", { name: "Filter tipe transaksi" }).click();
    await page.getByRole("option", { name: "Keluar" }).click();
    await expect(page.getByTestId("movement-row").first()).toContainText("Keluar");

    await page.getByRole("button", { name: "Unduh CSV" }).click();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("menuitem", { name: "Ringkasan per barang" }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^ringkasan-stok-\d{4}-\d{2}-\d{2}\.csv$/);
    const text = await (await download.createReadStream()).toArray().then((c) => Buffer.concat(c).toString("utf8"));
    expect(text.charCodeAt(0)).toBe(0xfeff);
    expect(text).toContain("Barcode;Kode Barang;Nama Barang");
    expect(text).toContain(m.barcode);
  });
});

test.describe("F-16 kartu stok & pembatalan oleh admin", () => {
  test("kartu stok menampilkan saldo & admin dapat membatalkan transaksi", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const m = p.variants[0];
    await admin.post("/api/v1/movements", {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: { type: "OUT", lines: [{ variant_id: m.id, qty: 4, reason: "damaged" }] },
    });
    await loginAsAdmin(page);
    await page.goto(`/barang/${p.id}`);
    await page.getByRole("button", { name: `Aksi varian ${m.barcode}` }).click();
    await page.getByRole("menuitem", { name: "Kartu stok" }).click();
    await expect(page.getByRole("heading", { name: "Kartu Stok" })).toBeVisible();
    const totals = page.getByTestId("stock-card-totals");
    await expect(totals).toContainText("Masuk10");
    await expect(totals).toContainText("Keluar4");
    await expect(page.getByTestId("movement-row")).toHaveCount(2);

    await page.getByTestId("movement-row").nth(1).getByRole("button", { name: /Batalkan transaksi/ }).click();
    await page.getByRole("dialog").getByLabel("Alasan pembatalan *").fill("Ternyata tidak rusak");
    await page.getByRole("dialog").getByRole("button", { name: "Batalkan transaksi" }).click();
    await expect(page.getByTestId("movement-row")).toHaveCount(3);
    await expect(totals).toContainText(/Saldo akhir.*10/);
  });
});

test.describe("F-02 kelola pengguna (UI)", () => {
  test("buat staf -> password sementara -> staf wajib ganti -> nonaktifkan", async ({ page, browser }) => {
    await loginAsAdmin(page);
    await page.goto("/pengguna");
    const email = `${uid("ui-")}@bhavia-e2e.com`;
    await page.getByRole("button", { name: "Tambah akun" }).click();
    await page.getByLabel("Nama").fill("Staf Gudang UI");
    await page.getByLabel("Email").fill(email);
    await page.getByRole("button", { name: "Simpan" }).click();
    const temp = (await page.getByTestId("temp-password").textContent())!.trim();
    expect(temp.length).toBeGreaterThanOrEqual(12);
    await page.getByRole("button", { name: "Selesai" }).click();
    const row = page.locator(`[data-testid=user-row][data-email="${email}"]`);
    await expect(row).toContainText("Menunggu ganti password");

    const staffCtx = await browser.newContext();
    const staffPage = await staffCtx.newPage();
    await login(staffPage, email, temp);
    await expect(staffPage).toHaveURL(/\/akun\?wajib=1/);
    // staf tidak melihat menu admin
    await expect(staffPage.getByRole("link", { name: "Laporan" })).toHaveCount(0);

    await row.getByRole("button", { name: `Aksi ${email}` }).click();
    await page.getByRole("menuitem", { name: "Nonaktifkan" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Nonaktifkan" }).click();
    await expect(row).toContainText("Nonaktif");
    await staffPage.reload();
    await expect(staffPage).toHaveURL(/\/login/);
    await staffCtx.close();
  });

  test("admin tidak bisa menonaktifkan diri sendiri; staf diblokir dari halaman admin", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/pengguna");
    const self = page.locator(`[data-testid=user-row][data-email="${ADMIN.email}"]`);
    await self.getByRole("button", { name: `Aksi ${ADMIN.email}` }).click();
    await expect(page.getByRole("menuitem", { name: "Nonaktifkan" })).toHaveCount(0);
    await page.keyboard.press("Escape");

    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const staff = await createStaff(admin, { password: "Rahasia-123" });
    await page.getByTestId("user-menu").click();
    await page.getByRole("menuitem", { name: "Keluar" }).click();
    await login(page, staff.email, staff.password);
    for (const path of ["/laporan", "/opname", "/pengguna"]) {
      await page.goto(path);
      await expect(page.getByText("Halaman ini khusus Admin.")).toBeVisible();
    }
    await createProduct(admin); // memastikan data tetap konsisten untuk tes berikutnya
  });
});
