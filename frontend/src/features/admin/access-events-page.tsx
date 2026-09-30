"use client";

import { History, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listAdminAccessEvents } from "./api";
import type { AdminAccessEvent } from "./types";
import { AdminEmpty, AdminPageHeader, AdminQueryState, AdminTableSkeleton, collectionItems, formatDate, formatLabel } from "./ui";

export function AdminAccessEventsPage() {
  const [search, setSearch] = useState("");
  const eventsQuery = useQuery({
    queryKey: ["admin", "access-events", search],
    queryFn: () => listAdminAccessEvents({ search })
  });
  const events = collectionItems(eventsQuery.data);

  return (
    <section className="page admin-page" aria-labelledby="access-events-title">
      <AdminPageHeader
        eyebrow="Privacy audit"
        title="Access log"
        description="A record of super-admin access to private account data."
        titleId="access-events-title"
      />
      <div className="toolbar admin-toolbar" role="search">
        <label className="search-field">
          <Search size={16} />
          <input className="toolbar-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search events" />
        </label>
        <button className="icon-button" type="button" onClick={() => void eventsQuery.refetch()} aria-label="Refresh access log"><RefreshCw size={16} /></button>
      </div>
      <AdminQueryState query={eventsQuery} loading={<AdminTableSkeleton columns={4} />}>
        {events.length ? <AdminEventsTable events={events} /> : <AdminEmpty title="No access events have been recorded." />}
      </AdminQueryState>
    </section>
  );
}

function AdminEventsTable({ events }: { events: AdminAccessEvent[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr><th className="table-heading">Event</th><th className="table-heading">Target</th><th className="table-heading">Contract</th><th className="table-heading">Time</th></tr></thead>
        <tbody>{events.map((event) => (
          <tr key={event.id}>
            <td className="table-cell"><span className="admin-event-name"><History size={15} /><span><strong>{formatLabel(event.event_type)}</strong><small>{event.actor_email || "Super admin"}</small></span></span></td>
            <td className="table-cell admin-muted">{event.target_user_email || "—"}</td>
            <td className="table-cell admin-muted">{event.contract_title || event.contract_id || "—"}</td>
            <td className="table-cell admin-muted">{formatDate(event.created_at)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

