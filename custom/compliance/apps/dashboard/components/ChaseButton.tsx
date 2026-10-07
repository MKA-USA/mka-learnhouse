"use client";

import { Link as HLink } from "@heroui/react";
import { useState } from "react";
import type { Filters } from "@/lib/queries";

function buildChaseUrl(filters: Filters) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v !== undefined) p.set(k, k === "region" && v === "" ? "_national" : k === "dept" && v === "" ? "executive" : v);
  return `/api/chase${p.size ? `?${p}` : ""}`;
}

export function ChaseButton({ filters, label = "Download chase list (CSV)" }: { filters: Filters; label?: string }) {
  return <HLink href={buildChaseUrl(filters)} download className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-fg shadow-sm hover:bg-primary/90">{label}</HLink>;
}

export function CopyEmailsButton({ filters }: { filters: Filters }) {
  const [copied, setCopied] = useState(false);
  const url = buildChaseUrl(filters);
  return (
    <button
      type="button"
      className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-surface-hover"
      onClick={async () => {
        try {
          const res = await fetch(`${url}&format=emails`);
          const text = await res.text();
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch {
          // fallback: fetch the CSV and extract email column
          const res = await fetch(url);
          const csv = await res.text();
          const lines = csv.split("\n").slice(1);
          const emails = lines.map((l) => l.split(",")[2]?.trim()).filter(Boolean);
          await navigator.clipboard.writeText(emails.join(", "));
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }
      }}
    >
      {copied ? "Copied!" : "Copy emails"}
    </button>
  );
}
