import { Table } from "@heroui/react";
import Link from "next/link";
import type { ScoredLearner } from "@mka/analytics/pure";
import { StatusChip } from "@/components/StatusChip";
import { EmptyState } from "@/components/StateViews";
import { ago, levelLabel, lessons, personLabel, regionLabel, shortDate } from "@/lib/format";

export const MAX_ROWS = 200;

export function PeopleTable({ rows, asOf, deptName, showDept = false, caption }: { rows: ScoredLearner[]; asOf: string; deptName: (slug: string) => string; showDept?: boolean; caption: string }) {
  if (!rows.length) return <EmptyState title="Nobody matches these filters" hint="Clear a filter to see more people." />;
  const shown = rows.slice(0, MAX_ROWS);
  return (
    <div className="space-y-2">
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label={caption} className="min-w-[760px]">
            <Table.Header>
              <Table.Column isRowHeader>Officeholder</Table.Column>
              <Table.Column>Role</Table.Column>
              <Table.Column>Status</Table.Column>
              <Table.Column>Lessons</Table.Column>
              <Table.Column>Last activity</Table.Column>
              <Table.Column>Due</Table.Column>
            </Table.Header>
            <Table.Body>
              {shown.map((r) => (
                <Table.Row key={r.rosterId} id={r.rosterId}>
                  <Table.Cell><Link className="font-medium hover:underline" href={`/person/${encodeURIComponent(r.rosterId)}`}>{personLabel(r)}</Link><span className="block text-xs text-muted">{r.email}</span></Table.Cell>
                  <Table.Cell>{r.roleTitle}<span className="block text-xs text-muted">{showDept ? `${deptName(r.departmentSlug)} · ` : ""}{r.majlis || regionLabel(r.region)} · {levelLabel(r.level)}</span></Table.Cell>
                  <Table.Cell><StatusChip status={r.status} />{r.daysOverdue ? <span className="ml-1 text-xs text-muted">{r.daysOverdue}d</span> : null}</Table.Cell>
                  <Table.Cell className="tabular-nums">{lessons(r)}</Table.Cell>
                  <Table.Cell>{ago(r.lastActivityAt, asOf)}</Table.Cell>
                  <Table.Cell>{shortDate(r.dueOn)}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
      {rows.length > MAX_ROWS ? <p className="text-xs text-muted">Showing the first {MAX_ROWS} of {rows.length}. Download the chase list for everyone.</p> : null}
    </div>
  );
}
