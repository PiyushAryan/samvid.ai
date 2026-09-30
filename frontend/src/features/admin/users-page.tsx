"use client";

import { ChevronRight, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@/lib/navigation";
import { listAdminUsers } from "./api";
import type { AdminUserSummary } from "./types";
import { AdminBadge, AdminEmpty, AdminPageHeader, AdminQueryState, AdminTableSkeleton, collectionItems, formatLabel, SummaryMetric } from "./ui";

export function AdminUsersPage() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const usersQuery = useQuery({
    queryKey: ["admin", "users", search, state],
    queryFn: () => listAdminUsers({ search, state })
  });
  const users = collectionItems(usersQuery.data);

  return (
    <section className="page admin-page" aria-labelledby="admin-users-title">
      <AdminPageHeader
        eyebrow="Platform oversight"
        title="User accounts"
        description="Read-only visibility across private Samvid accounts."
        titleId="admin-users-title"
      />
      <div className="admin-summary-strip" aria-label="Account summary">
        <SummaryMetric label="Visible accounts" value={String(users.length)} />
        <SummaryMetric label="Active" value={String(users.filter((item) => item.state === "active").length)} />
        <SummaryMetric label="Unclaimed" value={String(users.filter((item) => item.state === "unclaimed").length)} />
      </div>
      <div className="toolbar admin-toolbar" role="search">
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <input
            className="toolbar-input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name or email"
          />
        </label>
        <label className="toolbar-control">
          <span className="admin-control-label">State</span>
          <select className="toolbar-input" value={state} onChange={(event) => setState(event.target.value)} aria-label="Account state">
            <option value="">All states</option>
            <option value="active">Active</option>
            <option value="unclaimed">Unclaimed</option>
          </select>
        </label>
        <button className="icon-button" type="button" onClick={() => void usersQuery.refetch()} aria-label="Refresh users">
          <RefreshCw size={16} />
        </button>
      </div>
      <AdminQueryState query={usersQuery} loading={<AdminTableSkeleton columns={5} />}>
        {users.length ? <AdminUsersTable users={users} /> : <AdminEmpty title="No user accounts match these filters." />}
      </AdminQueryState>
    </section>
  );
}

function AdminUsersTable({ users }: { users: AdminUserSummary[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr>
          <th className="table-heading">Account</th>
          <th className="table-heading">State</th>
          <th className="table-heading">Source</th>
          <th className="table-heading">Contracts</th>
          <th className="table-heading"><span className="sr-only">Open</span></th>
        </tr></thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td className="table-cell">
                <Link className="admin-account-link" to={`/admin/users/${user.id}`}>
                  <span className="admin-avatar" aria-hidden="true">{(user.name || user.email).charAt(0).toUpperCase()}</span>
                  <span><strong>{user.name || "Unnamed account"}</strong><small>{user.email}</small></span>
                </Link>
              </td>
              <td className="table-cell"><AdminBadge value={user.state} /></td>
              <td className="table-cell admin-muted">{formatLabel(user.source)}</td>
              <td className="table-cell">{user.contract_count ?? 0}</td>
              <td className="table-cell admin-row-action"><Link to={`/admin/users/${user.id}`} aria-label={`Open ${user.email}`}><ChevronRight size={17} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

