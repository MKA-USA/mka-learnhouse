import { Chip } from "@heroui/react";
import type { Status } from "@mka/analytics/pure";
import { STATUS_META } from "@/lib/format";

export function StatusChip({ status }: { status: Status }) {
  const m = STATUS_META[status];
  return <Chip color={m.color} size="sm"><Chip.Label>{m.label}</Chip.Label></Chip>;
}
