import type { ReactNode } from "react";
import type { RiskSeverity } from "./types";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function PanelTitle({ children }: { children: ReactNode }) {
  return <h2>{children}</h2>;
}

export function EmptyState({ title }: { title: string }) {
  return <div className="empty">{title}</div>;
}

export function label(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusTone(status: string): string {
  if (["completed", "signed", "review_ready", "low"].includes(status)) return "success";
  if (["declined", "cancelled", "expired", "critical", "high", "parse_failed", "analysis_failed", "rejected_file"].includes(status)) return "danger";
  if (["sent", "viewed", "in_progress", "medium", "ocr_required", "analysing", "parsing"].includes(status)) return "warning";
  return "neutral";
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={cx("badge", statusTone(status))}>{label(status)}</span>;
}

function riskTone(status: string): string {
  if (status === "low") return "success";
  if (["critical", "high"].includes(status)) return "danger";
  if (status === "medium") return "warning";
  return "neutral";
}

export function RiskCounts({ counts }: { counts: Record<RiskSeverity, number> }) {
  const total = counts.critical + counts.high + counts.medium + counts.low;
  if (!total) return <span className="muted">None</span>;
  return (
    <span className="risk-counts">
      {(["critical", "high", "medium", "low"] as RiskSeverity[]).map((severity) =>
        counts[severity] ? <span className={cx("risk-dot", riskTone(severity))} key={severity}>{counts[severity]}</span> : null
      )}
    </span>
  );
}
