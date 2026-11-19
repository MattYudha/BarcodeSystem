import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { AuthGate, FullScreenLoader } from "@/components/app/auth-gate";

// Shell statis = loader; sesi & konten dimuat di client (data selalu dari API per user).
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<FullScreenLoader />}>
      <AuthGate>
        <AppShell>{children}</AppShell>
      </AuthGate>
    </Suspense>
  );
}
