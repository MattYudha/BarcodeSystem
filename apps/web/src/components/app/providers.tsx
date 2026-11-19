"use client";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError, errorMessage } from "@/lib/api/client";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        // Jangan ulangi error 4xx (izin, validasi, tidak ditemukan); ulangi gangguan jaringan/5xx.
        retry: (count, err) =>
          !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      },
      mutations: { retry: false },
    },
    mutationCache: new MutationCache({
      // Toast error otomatis untuk semua mutasi kecuali yang menangani sendiri (meta.silent).
      onError: (err, _vars, _ctx, mutation) => {
        if (mutation.meta?.silent) return;
        if (err instanceof ApiError && err.status === 401) return; // ditangani AuthGate
        toast.error(errorMessage(err));
      },
    }),
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={300}>
        {children}
        <Toaster position="top-center" richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
