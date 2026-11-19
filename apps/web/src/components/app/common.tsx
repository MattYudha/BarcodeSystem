"use client";

import { AlertTriangle, Inbox, Loader2, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/client";
import { useIsAdmin } from "@/lib/session";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const STATUS = {
  ok: { label: "Aman", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  low: { label: "Menipis", className: "bg-amber-50 text-amber-800 border-amber-200" },
  out: { label: "Habis", className: "bg-red-50 text-red-700 border-red-200" },
} as const;

export function StockBadge({ status }: { status: keyof typeof STATUS }) {
  const s = STATUS[status];
  return (
    <Badge variant="outline" className={cn("font-medium", s.className)}>
      {s.label}
    </Badge>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-background px-6 py-12 text-center">
      <Inbox className="size-8 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function LoadingBlock({ label = "Memuat…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-6 py-8 text-center">
      <AlertTriangle className="size-6 text-destructive" />
      <p className="text-sm">{errorMessage(error)}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Coba lagi
        </Button>
      )}
    </div>
  );
}

/** Halaman khusus admin. Server tetap menolak (403); ini hanya untuk UX. */
export function AdminOnly({ children }: { children: ReactNode }) {
  const isAdmin = useIsAdmin();
  if (isAdmin) return <>{children}</>;
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-center">
      <ShieldAlert className="size-8 text-muted-foreground" />
      <p className="font-medium">Halaman ini khusus Admin.</p>
      <p className="text-sm text-muted-foreground">Hubungi admin gudang jika Anda membutuhkan akses.</p>
    </div>
  );
}
