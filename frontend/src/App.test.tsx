import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell, ChatsPage, ContractsTableSkeleton, ContractTable, ReviewTab, Timeline } from "./App";
import { LandingPage } from "./Home";
import { TooltipProvider } from "./components/ui/tooltip";
import type { ContractListItem, ContractReview, SigningRequest } from "./types";

vi.mock("./AuthProvider", () => ({
  useAuth: () => ({
    user: {
      id: "user_123",
      name: "Piyush Aryan",
      email: "piyusharyan81@gmail.com",
      emailVerified: true
    },
    isLoading: false,
    refreshSession: vi.fn(),
    signOut: vi.fn()
  })
}));

test("landing simulator switches between customer workflow previews", async () => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

  render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  );

  expect(screen.getByRole("heading", { name: "Every contract your business touches." })).toBeInTheDocument();
  expect(screen.getByText("Re: Acme vendor agreement")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Review" }));
  expect(await screen.findByText("Review complete")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Signature" }));
  expect(await screen.findByText("Follow-up scheduled")).toBeInTheDocument();
});

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

test("sidebar control toggles its collapsed state", () => {
  render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/contracts"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/contracts" element={<div>Contracts page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );

  const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
  fireEvent.click(toggle);

  expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "true");
});

test("workspace view slider switches between console and chats", () => {
  const { container } = render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/contracts"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/contracts" element={<div>Contracts page</div>} />
            <Route path="/chats" element={<ChatsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );

  const consoleOption = within(container).getByRole("button", { name: /console/i });
  const chatsOption = within(container).getByRole("button", { name: /chats/i });
  expect(consoleOption).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(chatsOption);

  expect(chatsOption).toHaveAttribute("aria-pressed", "true");
  expect(consoleOption).toHaveAttribute("aria-pressed", "false");
  expect(within(container).getByRole("heading", { name: "Hello, Piyush Aryan" })).toBeInTheDocument();
  expect(within(container).getByText("find anything about your contracts")).toBeInTheDocument();
  const chatHistory = within(container).getByRole("region", { name: "Today" });
  expect(within(chatHistory).getByRole("button", { name: "New chat" })).toBeInTheDocument();
  expect(within(chatHistory).getAllByRole("button", { name: "chat" })).toHaveLength(2);
  expect(within(container).queryByRole("link", { name: "Contracts" })).not.toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: "Signing" })).not.toBeInTheDocument();
});

test("chat composer accepts a file attachment", () => {
  const { container } = render(
    <MemoryRouter>
      <ChatsPage />
    </MemoryRouter>
  );

  expect(within(container).getByText("Ask about a contract", { selector: "label" })).toHaveAttribute("for", "ai-chat-prompt");
  expect(within(container).getByRole("textbox")).toHaveAttribute("placeholder", "Ask a question about your contracts...");
  expect(within(container).getByRole("button", { name: "Attach files" })).toHaveTextContent("Drop to attach");
  expect(within(container).getByRole("button", { name: "Send message" })).toBeDisabled();

  const fileInput = container.querySelector<HTMLInputElement>(".ai-chat-file-input");
  expect(fileInput).not.toBeNull();
  fireEvent.change(fileInput!, {
    target: { files: [new File(["agreement"], "vendor-agreement.pdf", { type: "application/pdf" })] }
  });

  expect(within(container).getByText("vendor-agreement.pdf")).toBeInTheDocument();
  expect(within(container).getByRole("status")).toHaveTextContent("1 file attached");
  expect(within(container).getByRole("button", { name: "Send message" })).toBeEnabled();
});

test("sidebar actions menu opens and switches theme", () => {
  window.localStorage.setItem("samvid-theme", "light");

  const { container } = render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/contracts"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/contracts" element={<div>Contracts page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );

  const menuTrigger = within(container).getByRole("button", { name: /open (?:sidebar actions|account menu)/i });
  fireEvent.click(menuTrigger);

  expect(menuTrigger).toHaveAttribute("aria-expanded", "true");
  const menu = within(container).getByRole("menu", { name: /sidebar actions|account/i });
  expect(within(menu).getByRole("menuitem", { name: "Account: Piyush Aryan" })).toBeInTheDocument();
  expect(within(menu).getByText("piyusharyan81@gmail.com")).toBeInTheDocument();
  expect(within(menu).getByRole("menuitem", { name: "Settings" })).toHaveAttribute("aria-disabled", "true");
  expect(within(menu).getByRole("menuitem", { name: /log ?out/i })).toBeEnabled();

  fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: /dark mode/i }));

  expect(container.querySelector(".app-shell")).toHaveAttribute("data-theme", "dark");
  expect(window.localStorage.getItem("samvid-theme")).toBe("dark");
  expect(within(container).queryByRole("menu", { name: /sidebar actions|account/i })).not.toBeInTheDocument();
});

test("contract loading state exposes one accessible status and hides its placeholders", () => {
  const { container } = render(<ContractsTableSkeleton />);

  expect(within(container).getByRole("status")).toHaveTextContent("Loading contracts");
  expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(32);
  expect(container.querySelector(".contracts-skeleton")).toHaveAttribute("aria-hidden", "true");
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
