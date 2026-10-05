"use client";

import { Label, ListBox, Select } from "@heroui/react";
import { useRouter } from "next/navigation";
import { PERSONAS } from "@/lib/personas";

/** Fixture mode only: switch the simulated viewer to see each role's scope. */
export function PersonaSwitcher({ current }: { current: string }) {
  const router = useRouter();
  return (
    <Select className="w-64" aria-label="View as (demo)" value={current} onChange={(k) => { document.cookie = `dev_persona=${String(k)}; path=/; SameSite=Lax`; router.refresh(); }}>
      <Label className="sr-only">View as (demo)</Label>
      <Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
      <Select.Popover>
        <ListBox>{PERSONAS.map((p) => <ListBox.Item key={p.key} id={p.key} textValue={p.label}>{p.label}<ListBox.ItemIndicator /></ListBox.Item>)}</ListBox>
      </Select.Popover>
    </Select>
  );
}
