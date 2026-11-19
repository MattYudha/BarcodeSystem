"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Loader2, MoreHorizontal, Plus, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { AdminOnly, ErrorBlock, LoadingBlock, PageHeader } from "@/components/app/common";
import { Confirm } from "@/components/app/confirm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/format";
import { useUser } from "@/lib/session";

type User = Schemas["UserOut"];
const USERS = ["users"] as const;

/** Password sementara hanya ditampilkan sekali; admin menyampaikannya ke staf. */
function TempPasswordDialog({ email, password, onClose }: { email: string; password: string; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Password sementara</DialogTitle>
          <DialogDescription>
            Sampaikan ke pemilik akun <b>{email}</b>. Password ini hanya tampil sekali dan wajib diganti saat login pertama.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-lg bg-muted p-3">
          <code className="flex-1 text-lg font-semibold tracking-wider" data-testid="temp-password">{password}</code>
          <Button variant="outline" size="sm" onClick={() => navigator.clipboard?.writeText(password).then(() => toast.success("Disalin"))}>
            <Copy /> Salin
          </Button>
        </div>
        <DialogFooter><Button onClick={onClose}>Selesai</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UserFormDialog({ user, trigger, onTemp }: { user?: User; trigger: ReactNode; onTemp: (email: string, pw: string) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<User["role"]>(user?.role ?? "staff");
  const save = useMutation({
    mutationFn: async (): Promise<string | null> => {
      if (user) {
        await unwrap(api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: user.id } }, body: { name, role } }));
        return null;
      }
      const created = await unwrap<Schemas["UserCreatedOut"]>(api.POST("/api/v1/users", { body: { name, email, role } }));
      return created.temp_password ?? null;
    },
    onSuccess: async (tempPassword) => {
      await qc.invalidateQueries({ queryKey: USERS });
      setOpen(false);
      if (tempPassword) onTemp(email, tempPassword);
      else toast.success("Akun diperbarui");
      if (!user) { setName(""); setEmail(""); setRole("staff"); }
    },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <DialogHeader>
            <DialogTitle>{user ? "Ubah akun" : "Tambah akun"}</DialogTitle>
            {!user && <DialogDescription>Password sementara dibuat otomatis oleh sistem.</DialogDescription>}
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="u-name">Nama</Label>
            <Input id="u-name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="u-email">Email</Label>
            <Input id="u-email" type="email" required disabled={!!user} value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label>Peran</Label>
            <Select value={role} onValueChange={(v) => setRole(v as User["role"])}>
              <SelectTrigger className="w-full" aria-label="Peran"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="staff">Staf — scan masuk/keluar, lihat stok, cetak label</SelectItem>
                <SelectItem value="admin">Admin — semua fitur</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />} Simpan
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function UsersPage() {
  const me = useUser();
  const qc = useQueryClient();
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const users = useQuery({ queryKey: USERS, queryFn: () => unwrap<User[]>(api.GET("/api/v1/users")) });

  const setActive = (u: User, active: boolean) =>
    unwrap(api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: u.id } }, body: { is_active: active } }))
      .then(async () => {
        await qc.invalidateQueries({ queryKey: USERS });
        toast.success(active ? `${u.name} diaktifkan` : `${u.name} dinonaktifkan dan langsung keluar dari semua perangkat`);
      });
  const resetPassword = (u: User) =>
    unwrap<Schemas["TempPasswordOut"]>(api.POST("/api/v1/users/{user_id}/reset-password", { params: { path: { user_id: u.id } } }))
      .then((r) => setTemp({ email: u.email, password: r.temp_password }));

  return (
    <>
      <PageHeader
        title="Pengguna"
        description="Akun Admin dan Staf. Setiap transaksi mencatat siapa yang melakukannya."
        actions={
          <UserFormDialog onTemp={(email, password) => setTemp({ email, password })}
            trigger={<Button><Plus /> Tambah akun</Button>} />
        }
      />
      {users.isPending ? <LoadingBlock /> : users.isError ? <ErrorBlock error={users.error} onRetry={() => users.refetch()} /> : (
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Nama</TableHead>
                <TableHead>Peran</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Login terakhir</TableHead>
                <TableHead className="w-10 pr-6" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((u) => {
                const self = u.id === me.id;
                return (
                  <TableRow key={u.id} data-testid="user-row" data-email={u.email} className={!u.is_active ? "opacity-60" : undefined}>
                    <TableCell className="pl-6">
                      <span className="font-medium">{u.name}</span> {self && <Badge variant="outline" className="ml-1">Anda</Badge>}
                      <span className="block text-xs text-muted-foreground">{u.email}</span>
                    </TableCell>
                    <TableCell>
                      {u.role === "admin" ? <Badge><ShieldCheck /> Admin</Badge> : <Badge variant="secondary">Staf</Badge>}
                    </TableCell>
                    <TableCell>
                      {!u.is_active ? <Badge variant="outline">Nonaktif</Badge>
                        : u.must_change_password ? <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">Menunggu ganti password</Badge>
                        : <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">Aktif</Badge>}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{fmtDateTime(u.last_login_at)}</TableCell>
                    <TableCell className="pr-6">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Aksi ${u.email}`}><MoreHorizontal /></Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <UserFormDialog user={u} key={`${u.id}-${u.name}-${u.role}`} onTemp={() => undefined}
                            trigger={<DropdownMenuItem onSelect={(e) => e.preventDefault()}>Ubah nama / peran</DropdownMenuItem>} />
                          {!self && (
                            <>
                              <Confirm title={`Reset password ${u.name}?`}
                                description="Semua sesi akun ini langsung berakhir. Password sementara baru akan ditampilkan."
                                confirmLabel="Reset password" onConfirm={() => resetPassword(u)}
                                trigger={<DropdownMenuItem onSelect={(e) => e.preventDefault()}><KeyRound /> Reset password</DropdownMenuItem>} />
                              <DropdownMenuSeparator />
                              {u.is_active ? (
                                <Confirm destructive title={`Nonaktifkan ${u.name}?`}
                                  description="Akun tidak bisa login dan langsung keluar dari semua perangkat. Riwayat transaksinya tetap tersimpan."
                                  confirmLabel="Nonaktifkan" onConfirm={() => setActive(u, false)}
                                  trigger={<DropdownMenuItem variant="destructive" onSelect={(e) => e.preventDefault()}><UserX /> Nonaktifkan</DropdownMenuItem>} />
                              ) : (
                                <DropdownMenuItem onSelect={() => void setActive(u, true).catch((e: Error) => toast.error(e.message))}>
                                  <UserCheck /> Aktifkan kembali
                                </DropdownMenuItem>
                              )}
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}
      {temp && <TempPasswordDialog email={temp.email} password={temp.password} onClose={() => setTemp(null)} />}
    </>
  );
}

export default function PenggunaPage() {
  return (
    <AdminOnly>
      <UsersPage />
    </AdminOnly>
  );
}
