import {
  ClipboardCheck,
  FileBarChart,
  LayoutDashboard,
  Package,
  ScanBarcode,
  Tags,
  type LucideIcon,
  UserCog,
  Users,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  /** tampil di bottom bar HP */
  mobile?: boolean;
};

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, mobile: true },
  { href: "/scan", label: "Scan", icon: ScanBarcode, mobile: true },
  { href: "/barang", label: "Barang", icon: Package, mobile: true },
  { href: "/label", label: "Cetak Label", icon: Tags, mobile: true },
  { href: "/opname", label: "Stock Opname", icon: ClipboardCheck, adminOnly: true },
  { href: "/laporan", label: "Laporan", icon: FileBarChart, adminOnly: true },
  { href: "/pengguna", label: "Pengguna", icon: Users, adminOnly: true },
  { href: "/akun", label: "Akun Saya", icon: UserCog },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
