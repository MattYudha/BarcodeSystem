"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/common";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import { ME_KEY, useUser } from "@/lib/session";

function ChangePassword() {
  const user = useUser();
  const forced = useSearchParams().get("wajib") === "1" || user.must_change_password;
  const qc = useQueryClient();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm.length > 0 && next !== confirm;

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/auth/change-password", {
          body: { current_password: current, new_password: next },
        }),
      ),
    onSuccess: async () => {
      toast.success("Password berhasil diganti. Perangkat lain otomatis keluar.");
      setCurrent("");
      setNext("");
      setConfirm("");
      await qc.invalidateQueries({ queryKey: ME_KEY });
      if (forced) router.replace("/");
    },
  });

  return (
    <>
      <PageHeader title="Akun Saya" description={`${user.name} · ${user.email}`} />
      {forced && (
        <Alert className="mb-4 max-w-lg border-amber-300 bg-amber-50 text-amber-900">
          <ShieldAlert />
          <AlertTitle>Ganti password terlebih dahulu</AlertTitle>
          <AlertDescription>
            Akun Anda memakai password sementara dari admin. Buat password baru untuk melanjutkan.
          </AlertDescription>
        </Alert>
      )}
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Ganti password</CardTitle>
          <CardDescription>Minimal 8 karakter.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!mismatch) save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="current">Password saat ini</Label>
              <Input id="current" type="password" autoComplete="current-password" required
                value={current} onChange={(e) => setCurrent(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new">Password baru</Label>
              <Input id="new" type="password" autoComplete="new-password" required minLength={8}
                value={next} onChange={(e) => setNext(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="confirm">Ulangi password baru</Label>
              <Input id="confirm" type="password" autoComplete="new-password" required
                aria-invalid={mismatch} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              {mismatch && <p className="text-sm text-destructive">Password baru tidak sama.</p>}
            </div>
            <Button type="submit" disabled={save.isPending || mismatch} className="justify-self-start">
              {save.isPending && <Loader2 className="animate-spin" />}
              Simpan password
            </Button>
          </form>
        </CardContent>
      </Card>
    </>
  );
}

export default function AkunPage() {
  return (
    <Suspense>
      <ChangePassword />
    </Suspense>
  );
}
