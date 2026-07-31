import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { AppShell, ChatsPage, ContractDetailPage, ContractsPage, ContractsTableSkeleton, ContractTable, ReviewTab, Timeline } from "./App";
import { LandingPage } from "./Home";
import * as api from "./api";
import { TooltipProvider } from "./components/ui/tooltip";
import { setTestUrl } from "./test-navigation";
import type { ChatSession, ChatSessionSummary, ContractDetail, ContractListItem, ContractReview, SigningRequest } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    listChatSessions: vi.fn(),
    createChatSession: vi.fn(),
    getChatSession: vi.fn(),
    listContracts: vi.fn(),
    getContract: vi.fn(),
    getContractDocument: vi.fn(),
    deleteContract: vi.fn(),
    streamChatMessage: vi.fn()
  };
});

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

const chatSessions: ChatSessionSummary[] = [
  {
    id: "chat-1",
    title: "Vendor renewal terms",
    message_count: 2,
    created_at: "2026-07-20T09:00:00Z",
    updated_at: "2026-07-20T09:05:00Z"
  },
  {
    id: "chat-2",
    title: "Indemnity exposure",
    message_count: 4,
    created_at: "2026-07-19T09:00:00Z",
    updated_at: "2026-07-19T09:05:00Z"
  }
];

const chatSession: ChatSession = {
  ...chatSessions[0],
  messages: [
    {
      id: "message-1",
      role: "user",
      content: "When does the vendor agreement renew?",
      sources: [],
      created_at: "2026-07-20T09:00:00Z"
    },
    {
      id: "message-2",
      role: "assistant",
      content: "The agreement renews automatically for another 12 months.",
      sources: [
        {
          id: "source-1",
          contract_id: "contract-1",
          contract_title: "Vendor agreement",
          page_number: 7,
          excerpt: "The term automatically renews for successive twelve-month periods."
        }
      ],
      created_at: "2026-07-20T09:00:03Z"
    }
  ]
};

const contractDetail: ContractDetail = {
  id: "contract-delete",
  title: "Vendor agreement",
  review_status: "review_ready",
  created_by: "user@example.com",
  created_at: "2026-07-20T09:00:00Z",
  updated_at: "2026-07-20T09:05:00Z",
  current_version_id: null,
  current_version: null,
  original_filename: "vendor-agreement.pdf",
  mime_type: "application/pdf",
  risk_counts: { critical: 0, high: 1, medium: 0, low: 0 },
  signing_summary: {
    active_request_id: null,
    status: "not_started",
    required_signed: 0,
    required_total: 0,
    signer_total: 0
  },
  review: null,
  signing_requests: []
};

beforeEach(() => {
  vi.mocked(api.listChatSessions).mockResolvedValue(chatSessions);
  vi.mocked(api.getChatSession).mockResolvedValue(chatSession);
  vi.mocked(api.createChatSession).mockResolvedValue({
    id: "chat-new",
    title: "Termination notice",
    message_count: 0,
    created_at: "2026-07-20T10:00:00Z",
    updated_at: "2026-07-20T10:00:00Z",
    messages: []
  });
  vi.mocked(api.listContracts).mockResolvedValue([]);
  vi.mocked(api.getContract).mockResolvedValue(contractDetail);
  vi.mocked(api.getContractDocument).mockResolvedValue(new Blob());
  vi.mocked(api.deleteContract).mockResolvedValue(undefined);
  vi.mocked(api.streamChatMessage).mockResolvedValue(undefined);
});

function QueryProvider({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("landing simulator switches between customer workflow previews", async () => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

  render(<LandingPage />);

  expect(screen.getByRole("heading", { name: "Every contract your business touches." })).toBeInTheDocument();
  expect(screen.getByText("Re: Acme vendor agreement")).toBeInTheDocument();

  const inboxTab = screen.getByRole("tab", { name: "Inbox" });
  const reviewTab = screen.getByRole("tab", { name: "Review" });
  expect(inboxTab).toHaveAttribute("aria-controls", "preview-panel-intake");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "preview-panel-intake");

  inboxTab.focus();
  fireEvent.keyDown(inboxTab, { key: "ArrowRight" });
  expect(await screen.findByText("Review complete")).toBeInTheDocument();
  expect(reviewTab).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "preview-panel-review");

  fireEvent.click(screen.getByRole("tab", { name: "Signature" }));
  expect(await screen.findByText("Follow-up scheduled")).toBeInTheDocument();
});

test("contract refresh rotates until updated API data arrives", async () => {
  setTestUrl("/contracts");
  render(<QueryProvider><ContractsPage /></QueryProvider>);

  const refreshButton = screen.getByRole("button", { name: "Refresh contracts" });
  await waitFor(() => expect(refreshButton).not.toBeDisabled());

  let resolveRefresh!: (contracts: ContractListItem[]) => void;
  vi.mocked(api.listContracts).mockReturnValueOnce(new Promise((resolve) => {
    resolveRefresh = resolve;
  }));

  fireEvent.click(refreshButton);

  await waitFor(() => {
    expect(api.listContracts).toHaveBeenLastCalledWith({ search: "", reviewStatus: "", signingStatus: "" });
    expect(refreshButton).toBeDisabled();
    expect(refreshButton).toHaveAttribute("aria-busy", "true");
    expect(refreshButton.firstElementChild).toHaveClass("spin");
  });

  resolveRefresh([
    {
      id: "c-refreshed",
      title: "Refreshed services agreement",
      review_status: "review_ready",
      created_by: "legal@example.com",
      created_at: "2026-07-31T00:00:00Z",
      updated_at: "2026-07-31T00:05:00Z",
      current_version_id: "v-refreshed",
      original_filename: "services-agreement.pdf",
      mime_type: "application/pdf",
      risk_counts: { critical: 0, high: 0, medium: 1, low: 0 },
      signing_summary: {
        active_request_id: null,
        status: "not_started",
        required_signed: 0,
        required_total: 0,
        signer_total: 0
      }
    }
  ]);

  expect(await screen.findByRole("link", { name: "Refreshed services agreement" })).toBeInTheDocument();
  expect(refreshButton).not.toBeDisabled();
  expect(refreshButton).toHaveAttribute("aria-busy", "false");
  expect(refreshButton.firstElementChild).not.toHaveClass("spin");
});

test("contract listing renders signing counters and risk counts", () => {
  render(
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
  );

  expect(screen.getByRole("link", { name: "Vendor agreement" })).toBeInTheDocument();
  expect(screen.getByText("In Progress")).toBeInTheDocument();
  expect(screen.getByText("1/2 required")).toBeInTheDocument();
});

test("contract owner confirms permanent deletion and returns to the list", async () => {
  setTestUrl("/contracts/contract-delete");
  render(<QueryProvider><ContractDetailPage /></QueryProvider>);

  expect(await screen.findByRole("heading", { name: "Vendor agreement" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));

  const dialog = screen.getByRole("dialog", { name: "Delete contract" });
  expect(within(dialog).getByText(/original document, review, extracted knowledge/i)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Permanently delete" }));

  await waitFor(() => expect(api.deleteContract).toHaveBeenCalledWith("contract-delete"));
  expect(window.location.pathname).toBe("/contracts");
});

test("sidebar control toggles its collapsed state", () => {
  setTestUrl("/contracts");
  render(<TooltipProvider><AppShell><div>Contracts page</div></AppShell></TooltipProvider>);

  const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
  fireEvent.click(toggle);

  expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "true");
});

test("workspace view slider switches between console and loads chat history", async () => {
  setTestUrl("/contracts");
  const { container } = render(
    <QueryProvider>
      <TooltipProvider><AppShell><ChatsPage /></AppShell></TooltipProvider>
    </QueryProvider>
  );

  const consoleOption = within(container).getByRole("button", { name: /console/i });
  const chatsOption = within(container).getByRole("button", { name: /chats/i });
  expect(consoleOption).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(chatsOption);

  expect(chatsOption).toHaveAttribute("aria-pressed", "true");
  expect(consoleOption).toHaveAttribute("aria-pressed", "false");
  expect(within(container).getByRole("heading", { name: "Hello, Piyush" })).toBeInTheDocument();
  expect(within(container).getByText("find anything about your contracts")).toBeInTheDocument();
  fireEvent.click(within(container).getByRole("button", { name: "What changed in my latest contract?" }));
  expect(within(container).getByRole("textbox", { name: "Ask about a contract" })).toHaveValue(
    "What changed in my latest contract?"
  );
  const chatHistory = await within(container).findByRole("region", { name: "Chat history" });
  expect(within(chatHistory).getByRole("button", { name: "New chat" })).toBeInTheDocument();
  expect(await within(chatHistory).findByRole("button", { name: "Vendor renewal terms" })).toBeInTheDocument();
  expect(within(chatHistory).getByRole("button", { name: "Indemnity exposure" })).toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: "Contracts" })).not.toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: "Signing" })).not.toBeInTheDocument();
});

test("chat session renders persisted history and contract sources", async () => {
  setTestUrl("/chats?chat=chat-1");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  expect(within(container).getByText("Loading conversation")).toBeInTheDocument();
  expect(await within(container).findByText("The agreement renews automatically for another 12 months.")).toBeInTheDocument();
  const source = within(container).getByRole("link", { name: /Vendor agreement/i });
  expect(source).toHaveAttribute("href", "/contracts/contract-1");
  expect(within(container).getByText("Page 7")).toBeInTheDocument();
  expect(within(container).getByText(/successive twelve-month periods/)).toBeInTheDocument();
});

test("chat session exposes a recoverable history error", async () => {
  vi.mocked(api.getChatSession).mockRejectedValue(new Error("Knowledge index unavailable"));
  setTestUrl("/chats?chat=chat-missing");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  const alert = await within(container).findByRole("alert");
  expect(alert).toHaveTextContent("Conversation unavailable");
  expect(alert).toHaveTextContent("Knowledge index unavailable");
  expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
});

test("new chat streams an answer and exposes its sources", async () => {
  vi.mocked(api.streamChatMessage).mockImplementation(async (_sessionId, _content, handlers) => {
    handlers.onDelta?.("The termination notice is ");
    handlers.onDelta?.("30 days.");
    handlers.onSources?.([
      {
        contract_id: "contract-2",
        contract_title: "Services agreement",
        page_number: 11,
        excerpt: "Either party may terminate on thirty days' notice."
      }
    ]);
  });

  setTestUrl("/chats");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  const textbox = within(container).getByRole("textbox");
  fireEvent.change(textbox, { target: { value: "What is the termination notice?" } });
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(within(container).queryByRole("heading", { name: "Hello, Piyush" })).not.toBeInTheDocument();
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "true");
  await waitFor(() => expect(api.createChatSession).toHaveBeenCalledWith("What is the termination notice?"));
  expect(api.streamChatMessage).toHaveBeenCalledWith(
    "chat-new",
    "What is the termination notice?",
    expect.any(Object),
    expect.any(AbortSignal)
  );
  expect(await within(container).findByText("The termination notice is 30 days.")).toBeInTheDocument();
  expect(within(container).getByRole("link", { name: /Services agreement/i })).toHaveAttribute(
    "href",
    "/contracts/contract-2"
  );
});

test("new chats show the first message in the sidebar while the response is streaming", async () => {
  const prompt = "What is the termination notice?";
  vi.mocked(api.createChatSession).mockResolvedValueOnce({
    id: "chat-new",
    title: prompt,
    message_count: 0,
    created_at: "2026-07-20T10:00:00Z",
    updated_at: "2026-07-20T10:00:00Z",
    messages: []
  });
  vi.mocked(api.streamChatMessage).mockImplementationOnce(() => new Promise(() => undefined));

  setTestUrl("/chats");
  const { container } = render(
    <QueryProvider>
      <TooltipProvider><AppShell><ChatsPage /></AppShell></TooltipProvider>
    </QueryProvider>
  );
  await within(container).findByRole("button", { name: "Vendor renewal terms" });

  fireEvent.change(within(container).getByRole("textbox"), { target: { value: prompt } });
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(await within(container).findByRole("button", { name: prompt })).toBeInTheDocument();
  expect(api.streamChatMessage).toHaveBeenCalledWith(
    "chat-new",
    prompt,
    expect.any(Object),
    expect.any(AbortSignal)
  );
  expect(within(container).queryByRole("heading", { name: "Hello, Piyush" })).not.toBeInTheDocument();
  expect(within(container).getByText("Searching your contracts...")).toBeInTheDocument();
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "true");
});

test("new chat titles preserve normalized input up to the backend limit", async () => {
  const prompt = `  ${"a".repeat(181)}  `;
  const expectedTitle = `${"a".repeat(177)}...`;

  setTestUrl("/chats");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);
  fireEvent.change(within(container).getByRole("textbox"), { target: { value: prompt } });
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  await waitFor(() => expect(api.createChatSession).toHaveBeenCalledWith(expectedTitle));
});

test("a failed new chat returns to the welcome state and restores the draft", async () => {
  vi.mocked(api.createChatSession).mockRejectedValueOnce(new Error("Chat service unavailable"));

  setTestUrl("/chats");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);
  const textbox = within(container).getByRole("textbox");
  fireEvent.change(textbox, { target: { value: "Find my renewal date" } });
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(within(container).queryByRole("heading", { name: "Hello, Piyush" })).not.toBeInTheDocument();
  expect(await within(container).findByRole("alert")).toHaveTextContent("Chat service unavailable");
  expect(within(container).getByRole("heading", { name: "Hello, Piyush" })).toBeInTheDocument();
  expect(textbox).toHaveValue("Find my renewal date");
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "false");
});

test("sidebar actions menu opens and switches theme", () => {
  window.localStorage.setItem("samvid-theme", "light");

  setTestUrl("/contracts");
  const { container } = render(
    <TooltipProvider><AppShell><div>Contracts page</div></AppShell></TooltipProvider>
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
