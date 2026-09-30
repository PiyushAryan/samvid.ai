import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { CollectionResponse } from "./types";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function collectionItems<T>(response: CollectionResponse<T> | undefined): T[] {
  if (!response) return [];
  return Array.isArray(response) ? response : response.items;
}

export function AdminPageHeader({ eyebrow, title, description, titleId, action }: { eyebrow: string; title: string; description: string; titleId?: string; action?: ReactNode }) {
  return (
    <header className="page-header admin-page-header">
      <div><small>{eyebrow}</small><h1 id={titleId}>{title}</h1><p>{description}</p></div>
      {action}
    </header>
  );
}

export function SummaryMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

export function AdminBadge({ value }: { value: string }) {
  return <span className={cx("status", "admin-badge", `admin-badge-${value.replace(/_/g, "-")}`)}>{formatLabel(value)}</span>;
}

export function AdminEmpty({ title }: { title: string }) {
  return <div className="empty admin-empty"><ShieldCheck size={22} /><p>{title}</p></div>;
}

export function AdminQueryState({ query, loading, children }: { query: { isLoading: boolean; isError: boolean; error: unknown }; loading: ReactNode; children: ReactNode }) {
  if (query.isLoading) return loading;
  if (query.isError) return <div className="state error" role="alert">{query.error instanceof Error ? query.error.message : "Unable to load oversight data."}</div>;
  return children;
}

export function AdminTableSkeleton({ columns }: { columns: number }) {
  return <div className="admin-skeleton-table" role="status" aria-label="Loading data">{Array.from({ length: 4 * columns }, (_, index) => <Skeleton key={index} className="admin-skeleton-cell" />)}</div>;
}

export function AdminDetailSkeleton() {
  return <div className="admin-detail-skeleton" role="status" aria-label="Loading details"><Skeleton className="admin-skeleton-title" /><Skeleton /><Skeleton /><Skeleton /></div>;
}

export function AdminDocumentSkeleton() {
  return <div className="admin-document-skeleton" role="status" aria-label="Loading document"><Skeleton /></div>;
}

export function formatLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
