import { Link, Table } from "@heroui/react";
import type { ScoredLearner } from "@mka/analytics/pure";
import { StatusChip } from "@/components/StatusChip";
import { EmptyState } from "@/components/StateViews";
import { ago, levelLabel, lessons, personLabel, regionLabel, shortDate } from "@/lib/format";

export const PAGE_SIZE = 50;

export function PeopleTable({ rows, asOf, deptName, showDept = false, caption, page = 1, basePath }: { rows: ScoredLearner[]; asOf: string; deptName: (slug: string) => string; showDept?: boolean; caption: string; page?: number; basePath?: string }) {
  if (!rows.length) return <EmptyState title="Nobody matches these filters" hint="Clear a filter to see more people." />;
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const shown = rows.slice(start, start + PAGE_SIZE);
  return (
    <div className="space-y-3">
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
      {totalPages > 1 ? (
        <nav aria-label="People pagination" className="flex items-center justify-between text-sm">
          <span className="text-muted">Showing {start + 1}–{Math.min(start + PAGE_SIZE, rows.length)} of {rows.length}</span>
          {basePath ? (
            <div className="flex items-center gap-1">
              {currentPage > 1 ? <PaginationLink href={`${basePath}${basePath.includes("?") ? "&" : "?"}page=${currentPage - 1}`}>Previous</PaginationLink> : <span className="rounded-md px-3 py-1 text-muted opacity-50">Previous</span>}
              <span className="px-2 tabular-nums text-muted">{currentPage} / {totalPages}</span>
              {currentPage < totalPages ? <PaginationLink href={`${basePath}${basePath.includes("?") ? "&" : "?"}page=${currentPage + 1}`}>Next</PaginationLink> : <span className="rounded-md px-3 py-1 text-muted opacity-50">Next</span>}
            </div>
          ) : (
            <span className="text-xs text-muted">Page {currentPage} of {totalPages}</span>
          )}
        </nav>
      ) : null}
    </div>
  );
}

function PaginationLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="rounded-md border border-border px-3 py-1 hover:bg-surface-hover">{children}</Link>;
}
