import { expect, test, type Page } from "@playwright/test";

import { ADMIN, apiAs, createProduct, createStaff, json, login, loginAsAdmin } from "./support";

/** Simulasi scanner USB/Bluetooth: ketik sangat cepat + Enter saat fokus TIDAK di kolom isian. */
async function wedgeScan(page: Page, code: string) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.type(code, { delay: 5 });
  await page.keyboard.press("Enter");
}

async function stockOf(variantId: number) {
  const admin = await apiAs(ADMIN.email, ADMIN.password);
  return (await json(await admin.get(`/api/v1/variants/${variantId}`))).stock as number;
}

test.describe("Alur B & C: scan masuk/keluar", () => {
  test("scanner USB: scan dua kali = qty 2, simpan masuk menambah stok", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const m = p.variants[0];
    await loginAsAdmin(page);
    await page.goto("/scan");
    await expect(page.getByRole("radio", { name: "Barang masuk" })).toHaveAttribute("aria-checked", "true");

    await wedgeScan(page, m.barcode);
    await wedgeScan(page, m.barcode.toLowerCase()); // huruf kecil tetap dikenali
    const line = page.getByTestId("cart-line");
    await expect(line).toHaveCount(1);
    await expect(page.getByLabel(`Jumlah ${m.barcode}`)).toHaveValue("2");
    await expect(page.getByTestId("scan-log").locator("li")).toHaveCount(2);

    // ganti mode dikunci selama keranjang berisi
    await expect(page.getByRole("radio", { name: "Barang keluar" })).toBeDisabled();

    await page.getByLabel("Barcode", { exact: true }).fill(p.variants[1].barcode);
    await page.getByLabel("Barcode", { exact: true }).press("Enter");
    await expect(line).toHaveCount(2);
    await page.getByLabel(`Jumlah ${p.variants[1].barcode}`).fill("5");

    await page.getByRole("button", { name: /Simpan barang masuk \(7 pcs\)/ }).click();
    await expect(page.getByTestId("last-saved")).toContainText("Tersimpan");
    await expect(line).toHaveCount(0);
    expect(await stockOf(m.id)).toBe(12);
    expect(await stockOf(p.variants[1].id)).toBe(7);
    // langsung bisa cetak label untuk barang yang baru masuk
    await expect(page.getByTestId("last-saved").getByRole("link", { name: "Cetak label" }))
      .toHaveAttribute("href", new RegExp(`items=.*${m.id}:2`));
  });

  test("scanner mengetik ke kolom barcode yang sedang fokus -> satu scan utuh; ketik manual lambat juga bisa", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    await loginAsAdmin(page);
    await page.goto("/scan");
    const field = page.getByLabel("Barcode", { exact: true });
    await field.focus();
    await page.keyboard.type(p.variants[0].barcode, { delay: 5 }); // burst scanner
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("cart-line")).toHaveCount(1);
    await expect(field).toHaveValue("");
    await expect(page.getByTestId("scan-log").locator("li")).toHaveCount(1);

    await field.focus();
    await page.keyboard.type(p.variants[1].barcode, { delay: 90 }); // manusia mengetik
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("cart-line")).toHaveCount(2);
    await expect(page.getByTestId("scan-log").locator("li").first()).not.toContainText("tidak dikenal");
  });

  test("barcode tidak dikenal: pesan jelas & tidak masuk keranjang", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/scan");
    await wedgeScan(page, "BHV-0000-99");
    await expect(page.getByTestId("scan-log")).toContainText("Barcode tidak dikenal");
    await expect(page.getByTestId("cart-line")).toHaveCount(0);
  });

  test("keluar: tolak melebihi stok, alasan lainnya wajib catatan", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin); // L stok 2
    const l = p.variants[1];
    await loginAsAdmin(page);
    await page.goto("/scan");
    await page.getByRole("radio", { name: "Barang keluar" }).click();
    for (let i = 0; i < 3; i++) await wedgeScan(page, l.barcode);
    await expect(page.getByLabel(`Jumlah ${l.barcode}`)).toHaveValue("3");
    await expect(page.getByTestId("cart-line").getByRole("alert")).toContainText("Melebihi stok (tersedia 2)");
    const save = page.getByRole("button", { name: /Simpan barang keluar/ });
    await expect(save).toBeDisabled();

    await page.getByLabel(`Jumlah ${l.barcode}`).fill("2");
    await page.getByRole("combobox", { name: `Alasan ${l.barcode}` }).click();
    await page.getByRole("option", { name: "Lainnya" }).click();
    await expect(page.getByTestId("cart-line").getByRole("alert")).toContainText("Isi catatan");
    await page.getByLabel(`Catatan ${l.barcode}`).fill("Sampel pameran");
    await save.click();
    await expect(page.getByTestId("last-saved")).toBeVisible();
    expect(await stockOf(l.id)).toBe(0);

    const out = await json(await admin.get(`/api/v1/movements?variant_id=${l.id}&type=OUT`));
    expect(out.items[0]).toMatchObject({ qty: -2, reason: "other", note: "Sampel pameran", source: "scanner" });
  });

  test("klik Simpan berkali-kali tetap satu transaksi (idempotensi)", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const m = p.variants[0];
    await loginAsAdmin(page);
    await page.goto("/scan");
    await wedgeScan(page, m.barcode);
    const save = page.getByRole("button", { name: /Simpan barang masuk/ });
    await save.evaluate((btn: HTMLButtonElement) => { btn.click(); btn.click(); btn.click(); });
    await expect(page.getByTestId("last-saved")).toBeVisible();
    const ins = await json(await admin.get(`/api/v1/movements?variant_id=${m.id}&type=IN`));
    expect(ins.total).toBe(2); // stok awal + 1 scan
    expect(await stockOf(m.id)).toBe(11);
  });

  test("mode per item: Enter pada jumlah langsung menyimpan", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    await loginAsAdmin(page);
    await page.goto("/scan");
    await page.getByRole("tab", { name: "Per item" }).click();
    await wedgeScan(page, p.variants[0].barcode);
    await wedgeScan(page, p.variants[1].barcode); // mengganti item
    await expect(page.getByTestId("cart-line")).toHaveCount(1);
    await page.getByLabel(`Jumlah ${p.variants[1].barcode}`).fill("4");
    await page.getByLabel(`Jumlah ${p.variants[1].barcode}`).press("Enter");
    await expect(page.getByTestId("last-saved")).toBeVisible();
    expect(await stockOf(p.variants[1].id)).toBe(6);
  });

  test("staf membatalkan transaksinya sendiri dari halaman scan", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const staff = await createStaff(admin, { password: "Rahasia-123" });
    await login(page, staff.email, staff.password);
    await page.goto("/scan");
    await wedgeScan(page, p.variants[0].barcode);
    await page.getByRole("button", { name: /Simpan barang masuk/ }).click();
    await expect(page.getByTestId("last-saved")).toBeVisible();
    expect(await stockOf(p.variants[0].id)).toBe(11);

    const recent = page.getByTestId("recent-movements");
    await recent.getByRole("button", { name: /Batalkan transaksi/ }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Batalkan transaksi" })).toBeDisabled(); // alasan wajib
    await dialog.getByLabel("Alasan pembatalan *").fill("Salah scan");
    await dialog.getByRole("button", { name: "Batalkan transaksi" }).click();
    await expect(page.getByText("Transaksi dibatalkan")).toBeVisible();
    expect(await stockOf(p.variants[0].id)).toBe(10);
    await expect(recent.getByText("dibatalkan").first()).toBeVisible();
  });
});

test.describe("F-10 scan pakai kamera", () => {
  test("kamera membaca barcode label dan menambah ke keranjang", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const p = await createProduct(admin);
    const m = p.variants[0];

    // Kamera palsu: stream dari canvas yang menggambar barcode SVG asli dari API.
    await page.addInitScript(() => {
      const md = navigator.mediaDevices;
      md.getUserMedia = async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 1280;
        canvas.height = 720;
        const ctx = canvas.getContext("2d")!;
        const img = new Image();
        const src = (window as unknown as { __barcodeSrc?: string }).__barcodeSrc!;
        await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = src; });
        const draw = () => {
          ctx.fillStyle = "#fff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          const w = 1000;
          const h = (img.height / img.width) * w;
          ctx.drawImage(img, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
        };
        draw();
        setInterval(draw, 100);
        return canvas.captureStream(15);
      };
      md.enumerateDevices = async () => [{ kind: "videoinput", deviceId: "fake", label: "Kamera palsu", groupId: "g" } as MediaDeviceInfo];
    });

    await loginAsAdmin(page);
    await page.goto("/scan");
    await page.evaluate((id) => { (window as unknown as { __barcodeSrc: string }).__barcodeSrc = `/api/v1/variants/${id}/barcode.svg`; }, m.id);
    await page.getByRole("button", { name: "Scan pakai kamera" }).click();
    await expect(page.getByLabel("Pratinjau kamera")).toBeVisible();
    await expect(page.getByTestId("cart-line")).toHaveCount(1, { timeout: 20_000 });
    await expect(page.getByTestId("cart-line")).toHaveAttribute("data-barcode", m.barcode);
    // kamera masih mengarah ke barcode yang sama -> tidak menambah berkali-kali dalam 1,5 detik
    await page.waitForTimeout(800);
    await expect(page.getByLabel(`Jumlah ${m.barcode}`)).toHaveValue("1");
    await page.getByRole("button", { name: "Matikan kamera" }).click();

    await page.getByRole("button", { name: /Simpan barang masuk/ }).click();
    await expect(page.getByTestId("last-saved")).toBeVisible();
    const ins = await json(await admin.get(`/api/v1/movements?variant_id=${m.id}&type=IN`));
    expect(ins.items[0].source).toBe("camera");
  });

  test("tanpa HTTPS / izin ditolak: pesan jelas", async ({ page }) => {
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("denied", "NotAllowedError"); };
    });
    await loginAsAdmin(page);
    await page.goto("/scan");
    await page.getByRole("button", { name: "Scan pakai kamera" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Izin kamera ditolak" })).toBeVisible();
  });
});
