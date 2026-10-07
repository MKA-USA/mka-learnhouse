"use client";

import { Label, ListBox, SearchField, Select } from "@heroui/react";
import type { Key } from "@heroui/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";

export interface Option { id: string; label: string }
const ALL = "__all";

function Pick({ label, value, options, onChange }: { label: string; value: string; options: Option[]; onChange: (id: string) => void }) {
  return (
    <Select className="w-full sm:w-52" placeholder={label} value={value || ALL} onChange={(k: Key | null) => onChange(k === null || k === ALL ? "" : String(k))}>
      <Label>{label}</Label>
      <Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
      <Select.Popover>
        <ListBox>
          <ListBox.Item id={ALL} textValue={`All ${label.toLowerCase()}s`}>{`All ${label.toLowerCase()}s`}<ListBox.ItemIndicator /></ListBox.Item>
          {options.map((o) => <ListBox.Item key={o.id} id={o.id} textValue={o.label}>{o.label}<ListBox.ItemIndicator /></ListBox.Item>)}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

/** URL-driven filters (shareable, back-button friendly). Only narrows what the server already scoped. */
export function FilterBar({ regions, departments, statuses, show }: { regions?: Option[]; departments?: Option[]; statuses?: Option[]; show: ("dept" | "region" | "status" | "q")[] }) {
  const router = useRouter(), path = usePathname(), sp = useSearchParams();
  const [pending, start] = useTransition();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp.toString());
    if (v) next.set(k, v); else next.delete(k);
    start(() => router.replace(`${path}${next.size ? `?${next}` : ""}`, { scroll: false }));
  };
  return (
    <form role="search" aria-label="Filters" aria-busy={pending} onSubmit={(e) => { e.preventDefault(); set("q", q); }} className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
      {show.includes("dept") && departments ? <Pick label="Department" value={sp.get("dept") ?? ""} options={departments} onChange={(v) => set("dept", v)} /> : null}
      {show.includes("region") && regions ? <Pick label="Region" value={sp.get("region") ?? ""} options={regions} onChange={(v) => set("region", v)} /> : null}
      {show.includes("status") && statuses ? <Pick label="Status" value={sp.get("status") ?? ""} options={statuses} onChange={(v) => set("status", v)} /> : null}
      {show.includes("q") ? (
        <div className="flex w-full items-end gap-2 sm:w-auto">
          <SearchField className="w-full sm:w-64" name="q" value={q} onChange={setQ} onClear={() => set("q", "")}>
            <Label>Find a person</Label>
            <SearchField.Group><SearchField.SearchIcon /><SearchField.Input placeholder="Name, mailbox or Majlis" /><SearchField.ClearButton /></SearchField.Group>
          </SearchField>
          <button type="submit" className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-surface-hover">Search</button>
        </div>
      ) : null}
    </form>
  );
}
