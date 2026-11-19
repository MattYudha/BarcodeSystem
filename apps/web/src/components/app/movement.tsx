import { Badge } from "@/components/ui/badge";
import type { Movement } from "@/lib/api/client";
import { MOVEMENT_TYPES, OUT_REASONS } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE = {
  IN: "bg-emerald-50 text-emerald-700 border-emerald-200",
  OUT: "bg-sky-50 text-sky-700 border-sky-200",
  ADJUST: "bg-violet-50 text-violet-700 border-violet-200",
  REVERSAL: "bg-zinc-100 text-zinc-700 border-zinc-200",
} as const;

export function MovementTypeBadge({ movement }: { movement: Pick<Movement, "type" | "reversed_by"> }) {
  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant="outline" className={cn("font-medium", TONE[movement.type])}>
        {MOVEMENT_TYPES[movement.type]}
      </Badge>
      {movement.reversed_by != null && (
        <Badge variant="outline" className="border-dashed text-muted-foreground">
          dibatalkan
        </Badge>
      )}
    </span>
  );
}

export function reasonLabel(reason: Movement["reason"]): string {
  return reason ? OUT_REASONS[reason] : "";
}
