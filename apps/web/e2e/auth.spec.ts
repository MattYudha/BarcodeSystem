import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, createStaff, login, loginAsAdmin, uid } from "./support";

test.describe("F-01 login & sesi", () => {
  test("halaman terlindungi mengarah ke login lalu kembali ke tujuan", async ({ page }) => {
    await page.goto("/barang");
    await expect(page).toHaveURL(/\/login\?next=%2Fbarang/);
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Masuk" }).click();
    await expect(page).toHaveURL(/\/barang$/);
    await expect(page.getByRole("heading", { name: "Barang", exact: true })).toBeVisible();
  });

  test("password salah menampilkan pesan yang jelas", async ({ page }) => {
    await login(page, ADMIN.email, "salah-total", false);
    await expect(page.getByRole("alert").filter({ hasText: "Email atau password salah" })).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("open redirect ditolak", async ({ page }) => {
    await page.goto("/login?next=//evil.example.com");
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Masuk" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    expect(new URL(page.url()).host).toBe(new URL(page.url()).host);
    await expect(page).toHaveURL(/localhost:3000\/$/);
  });

  test("logout menghapus sesi", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("user-menu").click();
    await page.getByRole("menuitem", { name: "Keluar" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/barang");
    await expect(page).toHaveURL(/\/login/);
  });

  test("sesi dicabut di server -> otomatis ke login", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const staff = await createStaff(admin, { password: "Rahasia-123" });
    await login(page, staff.email, staff.password);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await admin.patch(`/api/v1/users/${staff.id}`, { data: { is_active: false } });
    await page.getByRole("link", { name: "Barang" }).first().click();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("F-02 akun staf", () => {
  test("staf baru dengan password sementara wajib ganti password", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const staff = await createStaff(admin);
    await login(page, staff.email, staff.password);
    await expect(page).toHaveURL(/\/akun\?wajib=1/);
    await expect(page.getByText("Ganti password terlebih dahulu")).toBeVisible();

    // tidak bisa kabur ke halaman lain sebelum ganti password
    await page.goto("/barang");
    await expect(page).toHaveURL(/\/akun\?wajib=1/);

    const newPassword = `Baru-${uid()}`;
    await page.getByLabel("Password saat ini").fill(staff.password);
    await page.getByLabel("Password baru", { exact: true }).fill(newPassword);
    await page.getByLabel("Ulangi password baru").fill(newPassword + "x");
    await expect(page.getByText("Password baru tidak sama")).toBeVisible();
    await page.getByLabel("Ulangi password baru").fill(newPassword);
    await page.getByRole("button", { name: "Simpan password" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  test("staf tidak melihat aksi admin", async ({ page }) => {
    const admin = await apiAs(ADMIN.email, ADMIN.password);
    const staff = await createStaff(admin, { password: "Rahasia-123" });
    await login(page, staff.email, staff.password);
    await page.goto("/barang");
    await expect(page.getByRole("heading", { name: "Barang", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Tambah barang" })).toHaveCount(0);
    await page.goto("/barang/baru");
    await expect(page.getByText("Halaman ini khusus Admin.")).toBeVisible();
  });
});
