"use client";

import { ArrowLeft, FileText, Search } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@/lib/navigation";
import { getAdminUser, listAdminUserContracts } from "./api";
import type { ContractListItem } from "@/features/contracts/types";
import { AdminBadge, AdminDetailSkeleton, AdminEmpty, AdminPageHeader, AdminQueryState, AdminTableSkeleton, collectionItems, formatDate, formatLabel } from "./ui";

export function AdminUserDetailPage() {
  const { userId = "" } = useParams();
  const [search, setSearch] = useState("");
  const userQuery = useQuery({
    queryKey: ["admin", "user", userId],
    queryFn: () => getAdminUser(userId),
    enabled: Boolean(userId)
  });
  const contractsQuery = useQuery({
    queryKey: ["admin", "user", userId, "contracts", search],
    queryFn: () => listAdminUserContracts(userId, { search }),
    enabled: Boolean(userId)
  });
  const contracts = collectionItems(contractsQuery.data);

  return (
    <section className="page admin-page">
      <Link className="admin-back-link" to="/admin/users"><ArrowLeft size={15} /> User accounts</Link>
      <AdminQueryState query={userQuery} loading={<AdminDetailSkeleton />}>
        {userQuery.data && (
          <>
            <AdminPageHeader
              eyebrow="Private account"
              title={userQuery.data.name || userQuery.data.email}
              description={userQuery.data.email}
            />
            <dl className="admin-account-facts">
              <div><dt>State</dt><dd><AdminBadge value={userQuery.data.state} /></dd></div>
              <div><dt>Source</dt><dd>{formatLabel(userQuery.data.source)}</dd></div>
              <div><dt>Contracts</dt><dd>{userQuery.data.contract_count ?? contracts.length}</dd></div>
              <div><dt>Joined</dt><dd>{formatDate(userQuery.data.claimed_at || userQuery.data.created_at)}</dd></div>
            </dl>
          </>
        )}
      </AdminQueryState>

      <section className="admin-section" aria-labelledby="user-contracts-title">
        <div className="admin-section-heading">
          <div><span>Private data</span><h2 id="user-contracts-title">Contracts</h2></div>
          <label className="search-field admin-inline-search">
            <Search size={15} />
            <input className="toolbar-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search contracts" />
          </label>
        </div>
        <AdminQueryState query={contractsQuery} loading={<AdminTableSkeleton columns={4} />}>
          {contracts.length ? <AdminContractsTable contracts={contracts} /> : <AdminEmpty title="This account has no matching contracts." />}
        </AdminQueryState>
      </section>
    </section>
  );
}

function AdminContractsTable({ contracts }: { contracts: ContractListItem[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr>
          <th className="table-heading">Contract</th>
          <th className="table-heading">Review</th>
          <th className="table-heading">Signing</th>
          <th className="table-heading">Updated</th>
        </tr></thead>
        <tbody>
          {contracts.map((contract) => (
            <tr key={contract.id}>
              <td className="table-cell"><Link className="admin-contract-link" to={`/admin/contracts/${contract.id}`}><FileText size={16} /><span><strong>{contract.title}</strong><small>{contract.original_filename}</small></span></Link></td>
              <td className="table-cell"><AdminBadge value={contract.review_status} /></td>
              <td className="table-cell"><AdminBadge value={contract.signing_summary?.status || "not_started"} /></td>
              <td className="table-cell admin-muted">{formatDate(contract.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

