import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ContractTable, ReviewTab, Timeline } from "./App";
import type { ContractListItem, ContractReview, SigningRequest } from "./types";

test("contract listing renders signing counters and risk counts", () => {
  render(
    <MemoryRouter>
      <ContractTable
        contracts={[
          {
            id: "c1",
            title: "Vendor agreement",
            review_status: "review_ready",
            created_by: "legal@example.com",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-02T00:00:00Z",
            current_version_id: "v1",
            original_filename: "vendor.txt",
            mime_type: "text/plain",
            risk_counts: { critical: 0, high: 1, medium: 2, low: 0 },
            signing_summary: {
              active_request_id: "sr1",
              status: "in_progress",
              required_signed: 1,
              required_total: 2,
              signer_total: 3
            }
          } satisfies ContractListItem
        ]}
      />
    </MemoryRouter>
  );

  expect(screen.getByRole("link", { name: "Vendor agreement" })).toBeInTheDocument();
  expect(screen.getByText("In Progress")).toBeInTheDocument();
  expect(screen.getByText("1/2 required")).toBeInTheDocument();
});

test("review tab renders evidence-grounded risks", () => {
  const review: ContractReview = {
    contract_id: "c1",
    contract_type: "Services agreement",
    parties: [],
    key_terms: [{ name: "Term", value: "12 months", confidence: 0.9 }],
    risks: [
      {
        title: "Unlimited liability",
        severity: "high",
        clause_type: "Liability",
        explanation: "The cap is missing.",
        recommendation: "Add a liability cap.",
        evidence: { page_number: 2, exact_text: "liability shall be unlimited" },
        confidence: 0.95
      }
    ],
    recommended_next_action: "Request revisions.",
    limitations: ["Not legal advice."]
  };

  render(<ReviewTab review={review} />);

  expect(screen.getByText("Services agreement")).toBeInTheDocument();
  expect(screen.getByText("Unlimited liability")).toBeInTheDocument();
  expect(screen.getByText(/Page 2: liability shall be unlimited/)).toBeInTheDocument();
});

test("timeline renders immutable events in chronological order", () => {
  const request: SigningRequest = {
    id: "sr1",
    workspace_id: "W1",
    contract_id: "c1",
    contract_version_id: "v1",
    status: "in_progress",
    active: true,
    created_by: "actor@example.com",
    created_at: "2026-01-01T00:00:00Z",
    closed_at: null,
    signers: [
      {
        id: "s1",
        name: "Asha",
        email: "asha@example.com",
        role: "Buyer",
        required: true,
        display_order: 0,
        latest_status: "viewed",
        created_at: "2026-01-01T00:00:00Z",
        events: [
          {
            id: "e2",
            signer_id: "s1",
            status: "viewed",
            note: "Viewed",
            actor_email: "actor@example.com",
            actor_name: "Actor",
            created_at: "2026-01-01T10:00:00Z"
          },
          {
            id: "e1",
            signer_id: "s1",
            status: "sent",
            note: "Sent",
            actor_email: "actor@example.com",
            actor_name: "Actor",
            created_at: "2026-01-01T09:00:00Z"
          }
        ]
      }
    ]
  };

  render(<Timeline request={request} />);

  const timeline = screen.getByLabelText("Immutable signer event timeline");
  const notes = within(timeline).getAllByText(/Sent|Viewed/, { selector: "p" }).map((node) => node.textContent);
  expect(notes).toEqual(["Sent", "Viewed"]);
});
