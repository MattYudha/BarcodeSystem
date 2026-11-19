"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Me } from "@/lib/api/client";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => unwrap<Me>(api.GET("/api/v1/auth/me")),
    staleTime: 60_000,
    retry: false,
  });
}

/** User yang sudah pasti login (dipakai di dalam AuthGate). */
export function useUser(): Me {
  const { data } = useMe();
  if (!data) throw new Error("useUser dipakai di luar AuthGate");
  return data;
}

export function useIsAdmin(): boolean {
  return useMe().data?.role === "admin";
}
