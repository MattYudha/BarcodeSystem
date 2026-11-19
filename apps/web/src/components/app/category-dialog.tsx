"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap, type Category } from "@/lib/api/client";

export function NewCategoryDialog({
  trigger,
  onCreated,
}: {
  trigger: ReactNode;
  onCreated: (c: Category) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => unwrap<Category>(api.POST("/api/v1/categories", { body: { name } })),
    onSuccess: async (c) => {
      await qc.invalidateQueries({ queryKey: ["categories"] });
      toast.success(`Kategori "${c.name}" dibuat`);
      onCreated(c);
      setName("");
      setOpen(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>Kategori baru</DialogTitle>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="cat-name">Nama kategori</Label>
            <Input id="cat-name" required maxLength={60} placeholder="mis. Kemeja"
              value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              {create.isPending && <Loader2 className="animate-spin" />} Simpan
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
