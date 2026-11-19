import {
  LayoutDashboard,
  Package,
  Tags,
  type LucideIcon,
  UserCog,
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
  { href: "/barang", label: "Barang", icon: Package, mobile: true },
  { href: "/label", label: "Cetak Label", icon: Tags, mobile: true },
  { href: "/akun", label: "Akun Saya", icon: UserCog },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
