"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap, uuid, type Movement } from "@/lib/api/client";
import { MOVEMENT_TYPES, variantLabel } from "@/lib/format";

/** Pembatalan transaksi = transaksi pembalik (riwayat asli tetap ada). Wajib alasan. */
export function ReverseButton({ movement, size = "sm" }: { movement: Movement; size?: "sm" | "xs" }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [key] = useState(uuid); // idempotensi: klik ganda tidak membuat pembatalan ganda
  const qc = useQueryClient();
  const reverse = useMutation({
    mutationFn: () =>
      unwrap<Movement>(
        api.POST("/api/v1/movements/{movement_id}/reverse", {
          params: { path: { movement_id: movement.id }, header: { "Idempotency-Key": key } },
          body: { note },
        }),
      ),
    onSuccess: async () => {
      await qc.invalidateQueries();
      toast.success("Transaksi dibatalkan. Stok sudah dikembalikan.");
      setOpen(false);
    },
  });
  if (!movement.can_reverse) return null;
  const sign = movement.qty > 0 ? `+${movement.qty}` : String(movement.qty);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size={size} aria-label={`Batalkan transaksi #${movement.id}`}>
          <Undo2 /> Batalkan
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); reverse.mutate(); }}>
          <DialogHeader>
            <DialogTitle>Batalkan transaksi #{movement.id}?</DialogTitle>
            <DialogDescription>
              {MOVEMENT_TYPES[movement.type]} {sign} — {movement.variant.product_name} (
              {variantLabel(movement.variant)}). Sistem membuat transaksi pembalik; riwayat asli tetap tersimpan.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`rev-${movement.id}`}>Alasan pembatalan *</Label>
            <Textarea id={`rev-${movement.id}`} required maxLength={500} rows={2}
              placeholder="mis. salah scan / jumlah keliru" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" variant="destructive" disabled={reverse.isPending || !note.trim()}>
              {reverse.isPending && <Loader2 className="animate-spin" />} Batalkan transaksi
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
