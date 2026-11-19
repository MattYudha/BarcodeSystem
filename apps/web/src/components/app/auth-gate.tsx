"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { UNAUTHENTICATED_EVENT } from "@/lib/api/client";
import { useMe } from "@/lib/session";

export function FullScreenLoader() {
  return (
    <div className="flex min-h-dvh items-center justify-center text-muted-foreground">
      <Loader2 className="mr-2 size-5 animate-spin" /> Memuat…
    </div>
  );
}

/**
 * Memastikan sesi valid sebelum merender aplikasi:
 * - 401 dari API mana pun -> bersihkan cache & ke /login?next=…
 * - akun wajib ganti password -> hanya boleh di /akun
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();

  useEffect(() => {
    const onUnauth = () => {
      qc.clear();
      const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    };
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauth);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauth);
  }, [qc, router, pathname]);

  const mustChange = me.data?.must_change_password && pathname !== "/akun";
  useEffect(() => {
    if (mustChange) router.replace("/akun?wajib=1");
  }, [mustChange, router]);

  if (me.isError && me.error && !("status" in me.error && me.error.status === 401)) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="font-medium">Tidak dapat memuat sesi.</p>
        <p className="text-sm text-muted-foreground">{me.error.message}</p>
        <button className="text-sm text-primary underline" onClick={() => me.refetch()}>
          Coba lagi
        </button>
      </div>
    );
  }
  if (!me.data || mustChange) return <FullScreenLoader />;
  return <>{children}</>;
}
