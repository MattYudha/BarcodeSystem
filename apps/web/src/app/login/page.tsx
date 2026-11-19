"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Shirt } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, errorMessage, unwrap, type Me } from "@/lib/api/client";
import { ME_KEY, useMe } from "@/lib/session";

/** Hanya path internal (cegah open redirect ke domain lain). */
function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/login")) return "/";
  return raw;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const qc = useQueryClient();
  const me = useMe();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Sudah login (cookie masih valid) -> langsung masuk.
  useEffect(() => {
    if (me.data) router.replace(me.data.must_change_password ? "/akun?wajib=1" : next);
  }, [me.data, next, router]);

  const login = useMutation({
    meta: { silent: true },
    mutationFn: () =>
      unwrap<Me>(api.POST("/api/v1/auth/login", { body: { email, password } })),
    onSuccess: (user) => {
      qc.setQueryData(ME_KEY, user);
      router.replace(user.must_change_password ? "/akun?wajib=1" : next);
    },
  });

  return (
    <Card className="w-full max-w-sm shadow-lg">
      <CardHeader className="items-center text-center">
        <span className="mx-auto mb-2 flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow">
          <Shirt className="size-6" />
        </span>
        <CardTitle className="text-xl">Bhavia Inventory</CardTitle>
        <CardDescription>Masuk untuk mengelola stok gudang</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            login.mutate();
          }}
        >
          {login.isError && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{errorMessage(login.error)}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              inputMode="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" size="lg" disabled={login.isPending}>
            {login.isPending && <Loader2 className="animate-spin" />}
            Masuk
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-gradient-to-b from-primary/10 to-muted/40 p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
