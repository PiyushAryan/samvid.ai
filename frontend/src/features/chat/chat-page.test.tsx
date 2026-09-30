import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AppShell } from "@/features/workspace/app-shell";
import { ChatsPage } from "@/features/chat/chat-page";
import { ContractDetailPage } from "@/features/contracts/contract-detail-page";
import { ContractsPage, ContractsTableSkeleton, ContractTable } from "@/features/contracts/contracts-page";
import { ReviewTab, RisksTab } from "@/features/contracts/review-components";
import { Timeline } from "@/features/signing/timeline";
import { LandingPage } from "@/features/marketing/landing-page";
import { IntegrationsPage } from "@/features/settings/integrations";
import { SettingsPage } from "@/features/settings/settings-page";
import * as settingsApi from "@/features/settings/api";
import * as contractApi from "@/features/contracts/api";
import * as chatApi from "@/features/chat/api";
import { TooltipProvider } from "@/components/ui/tooltip";
import { setTestUrl } from "@/test/mocks/next-navigation";
import type { ChatSession, ChatSessionSummary } from "@/features/chat/types";
import type { ContractDetail, ContractListItem, ContractReview } from "@/features/contracts/types";
import type { SigningRequest } from "@/features/signing/types";

vi.mock("@/features/settings/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/settings/api")>();
  return {
    ...actual,
    getSlackIntegration: vi.fn(),
    beginSlackInstallation: vi.fn(),
    disconnectSlackInstallation: vi.fn()
  };
});

vi.mock("@/features/chat/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/chat/api")>();
  return {
    ...actual,
    listChatSessions: vi.fn(),
    createChatSession: vi.fn(),
    getChatSession: vi.fn(),
    updateChatContractScope: vi.fn(),
    streamChatMessage: vi.fn()
  };
});

vi.mock("@/features/contracts/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/contracts/api")>();
  return {
    ...actual,
    listContracts: vi.fn(),
    getContract: vi.fn(),
    getContractDocument: vi.fn(),
    deleteContract: vi.fn(),
    uploadContract: vi.fn()
  };
});

vi.mock("@/features/auth/auth-provider", () => ({
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

vi.mock("@/features/chat/contract-mention-composer", async () => {
  const React = await import("react");
  return {
    ContractMentionComposer: (props: any) => {
      const [value, setValue] = React.useState("");
      React.useEffect(() => {
        const insertSuggestion = (event: Event) => setValue((event as CustomEvent<string>).detail);
        window.addEventListener("samvid:chat-suggestion", insertSuggestion);
        const reset = () => setValue("");
        window.addEventListener("samvid:new-chat", reset);
        return () => {
          window.removeEventListener("samvid:chat-suggestion", insertSuggestion);
          window.removeEventListener("samvid:new-chat", reset);
        };
      }, []);
      return React.createElement(
        "form",
        { onSubmit: (event: any) => { event.preventDefault(); void props.onSubmit({ content: value, contractId: null }); } },
        React.createElement("textarea", {
          "aria-label": "Ask about a contract",
          disabled: props.disabled || props.isSending,
          onChange: (event: any) => setValue(event.currentTarget.value),
          value
        }),
        React.createElement("button", { disabled: !value || props.disabled || props.isSending, type: "submit" }, "Send message"),
        props.error ? React.createElement("p", { role: "alert" }, props.error) : null
      );
    }
  };
});

const chatSessions: ChatSessionSummary[] = [
  {
    id: "chat-1",
    title: "Vendor renewal terms",
    contract_id: "contract-1",
    contract_title: "Vendor agreement",
    message_count: 2,
    created_at: "2026-07-20T09:00:00Z",
    updated_at: "2026-07-20T09:05:00Z"
  },
  {
    id: "chat-2",
    title: "Indemnity exposure",
    contract_id: null,
    contract_title: null,
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
  vi.mocked(chatApi.listChatSessions).mockResolvedValue(chatSessions);
  vi.mocked(chatApi.getChatSession).mockResolvedValue(chatSession);
  vi.mocked(chatApi.createChatSession).mockResolvedValue({
    id: "chat-new",
    title: "Termination notice",
    contract_id: null,
    contract_title: null,
    message_count: 0,
    created_at: "2026-07-20T10:00:00Z",
    updated_at: "2026-07-20T10:00:00Z",
    messages: []
  });
  vi.mocked(contractApi.listContracts).mockResolvedValue([]);
  vi.mocked(contractApi.getContract).mockResolvedValue(contractDetail);
  vi.mocked(contractApi.getContractDocument).mockResolvedValue(new Blob());
  vi.mocked(contractApi.deleteContract).mockResolvedValue(undefined);
  vi.mocked(contractApi.uploadContract).mockResolvedValue({
    contract_id: "contract-uploaded",
    contract_version_id: "version-uploaded",
    status: "queued",
    message: "Contract accepted and queued for review."
  });
  vi.mocked(chatApi.streamChatMessage).mockResolvedValue(undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function QueryProvider({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function enterChatText(textbox: HTMLElement, value: string) {
  if (textbox instanceof HTMLTextAreaElement) {
    fireEvent.change(textbox, { target: { value } });
    return;
  }
  textbox.textContent = value;
  fireEvent.input(textbox, { inputType: "insertText", data: value });
}

test("chat session renders persisted history without visible source citations", async () => {
  setTestUrl("/chats?chat=chat-1");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  expect(within(container).getByText("Loading conversation")).toBeInTheDocument();
  expect(await within(container).findByText("The agreement renews automatically for another 12 months.")).toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: /Vendor agreement/i })).not.toBeInTheDocument();
  expect(within(container).queryByText("Page 7")).not.toBeInTheDocument();
});

test("assistant replies render Markdown headings and lists", async () => {
  vi.mocked(chatApi.getChatSession).mockResolvedValueOnce({
    ...chatSession,
    messages: [{
      id: "message-markdown",
      role: "assistant",
      content: "## Summary\n\n- **Notice period:** Thirty days [S1]\n- **Renewal:** Annual [S2]",
      sources: [],
      created_at: "2026-07-20T10:00:00Z"
    }]
  });
  setTestUrl("/chats?chat=chat-markdown");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  expect(await within(container).findByRole("heading", { name: "Summary" })).toBeInTheDocument();
  expect(within(container).getByRole("list")).toHaveTextContent("Notice period: Thirty days");
  expect(within(container).getByRole("list")).toHaveTextContent("Renewal: Annual");
  expect(within(container).getByRole("list")).not.toHaveTextContent("[S1]");
  expect(within(container).getByRole("list")).not.toHaveTextContent("[S2]");
});

test("assistant citations remain internal to the rendered response", async () => {
  vi.mocked(chatApi.getChatSession).mockResolvedValueOnce({
    ...chatSession,
    messages: [{
      id: "message-citation",
      role: "assistant",
      content: "The notice period is thirty days. [S1]",
      sources: [{
        id: "S1",
        contract_id: "contract-1",
        contract_title: "Services agreement",
        page_number: 11,
        excerpt: "Either party may terminate on thirty days' notice."
      }],
      created_at: "2026-07-20T10:00:00Z"
    }]
  });
  setTestUrl("/chats?chat=chat-citation");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  expect(await within(container).findByText("The notice period is thirty days.")).toBeInTheDocument();
  expect(within(container).queryByRole("button", { name: /view source/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("blockquote")).not.toBeInTheDocument();
});

test("chat session exposes a recoverable history error", async () => {
  vi.mocked(chatApi.getChatSession).mockRejectedValue(new Error("Knowledge index unavailable"));
  setTestUrl("/chats?chat=chat-missing");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);

  const alert = await within(container).findByRole("alert");
  expect(alert).toHaveTextContent("Conversation unavailable");
  expect(alert).toHaveTextContent("Knowledge index unavailable");
  expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
});

test("new chat streams an answer and exposes its sources", async () => {
  vi.mocked(chatApi.streamChatMessage).mockImplementation(async (_sessionId, _content, handlers) => {
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
  enterChatText(textbox, "What is the termination notice?");
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(within(container).queryByRole("heading", { name: /Piyush/ })).not.toBeInTheDocument();
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "true");
  await waitFor(() => expect(chatApi.createChatSession).toHaveBeenCalledWith("What is the termination notice?"));
  expect(chatApi.streamChatMessage).toHaveBeenCalledWith(
    "chat-new",
    "What is the termination notice?",
    expect.any(Object),
    expect.any(AbortSignal)
  );
  expect(await within(container).findByText("The termination notice is 30 days.")).toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: /Services agreement/i })).not.toBeInTheDocument();
});

test("new chats show the first message in the sidebar while the response is streaming", async () => {
  const prompt = "What is the termination notice?";
  let streamSignal: AbortSignal | undefined;
  vi.mocked(chatApi.createChatSession).mockResolvedValueOnce({
    id: "chat-new",
    title: prompt,
    contract_id: null,
    contract_title: null,
    message_count: 0,
    created_at: "2026-07-20T10:00:00Z",
    updated_at: "2026-07-20T10:00:00Z",
    messages: []
  });
  vi.mocked(chatApi.streamChatMessage).mockImplementationOnce((_sessionId, _content, handlers, signal) => {
    streamSignal = signal;
    handlers.onStatus?.("Reading relevant contract evidence...");
    return new Promise(() => undefined);
  });

  setTestUrl("/chats");
  const { container } = render(
    <QueryProvider>
      <TooltipProvider><AppShell><ChatsPage /></AppShell></TooltipProvider>
    </QueryProvider>
  );
  await within(container).findByRole("button", { name: "Vendor renewal terms" });

  enterChatText(within(container).getByRole("textbox"), prompt);
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(await within(container).findByRole("button", { name: prompt })).toBeInTheDocument();
  expect(chatApi.streamChatMessage).toHaveBeenCalledWith(
    "chat-new",
    prompt,
    expect.any(Object),
    expect.any(AbortSignal)
  );
  expect(streamSignal?.aborted).toBe(false);
  expect(within(container).queryByRole("heading", { name: /Piyush/ })).not.toBeInTheDocument();
  expect(within(container).getByText("Reading relevant contract evidence...")).toBeInTheDocument();
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "true");

  fireEvent.click(within(container).getByRole("button", { name: "New chat" }));

  expect(streamSignal?.aborted).toBe(true);
  expect(await within(container).findByRole("heading", { name: /Piyush/ })).toBeInTheDocument();
  expect(within(container).getByRole("textbox", { name: "Ask about a contract" })).toHaveValue("");
  expect(window.location.pathname).toBe("/chats");
  expect(window.location.search).toBe("");
});

test("new chat titles preserve normalized input up to the backend limit", async () => {
  const prompt = `  ${"a".repeat(181)}  `;
  const expectedTitle = `${"a".repeat(177)}...`;

  setTestUrl("/chats");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);
  enterChatText(within(container).getByRole("textbox"), prompt);
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  await waitFor(() => expect(chatApi.createChatSession).toHaveBeenCalledWith(expectedTitle));
});

test("a failed new chat returns to the welcome state and restores the draft", async () => {
  vi.mocked(chatApi.createChatSession).mockRejectedValueOnce(new Error("Chat service unavailable"));

  setTestUrl("/chats");
  const { container } = render(<QueryProvider><ChatsPage /></QueryProvider>);
  const textbox = within(container).getByRole("textbox");
  enterChatText(textbox, "Find my renewal date");
  fireEvent.click(within(container).getByRole("button", { name: "Send message" }));

  expect(within(container).queryByRole("heading", { name: /Piyush/ })).not.toBeInTheDocument();
  expect(await within(container).findByRole("alert")).toHaveTextContent("Chat service unavailable");
  expect(within(container).getByRole("heading", { name: /Piyush/ })).toBeInTheDocument();
  expect(textbox).toHaveValue("Find my renewal date");
  expect(container.querySelector(".ai-chat-page")).toHaveAttribute("data-conversation", "false");
});

