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
  expect(within(container).getByRole("heading", { name: /Piyush/ })).toBeInTheDocument();
  expect(within(container).getByText("find anything about your contracts")).toBeInTheDocument();
  fireEvent.click(within(container).getByRole("button", { name: "What changed in my latest contract?" }));
  expect(within(container).getByRole("textbox", { name: "Ask about a contract" })).toHaveTextContent(
    "What changed in my latest contract?"
  );
  const chatHistory = await within(container).findByRole("region", { name: "Chat history" });
  expect(within(chatHistory).getByRole("button", { name: "New chat" })).toBeInTheDocument();
  expect(await within(chatHistory).findByRole("button", { name: "Vendor renewal terms" })).toBeInTheDocument();
  expect(within(chatHistory).getByRole("button", { name: "Indemnity exposure" })).toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: "Contracts" })).not.toBeInTheDocument();
  expect(within(container).queryByRole("link", { name: "Signing" })).not.toBeInTheDocument();
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
  expect(within(menu).getByRole("menuitem", { name: "Settings" })).toBeEnabled();
  expect(within(menu).getByRole("menuitem", { name: /log ?out/i })).toBeEnabled();

  fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: /dark mode/i }));

  expect(container.querySelector(".app-shell")).toHaveAttribute("data-theme", "dark");
  expect(window.localStorage.getItem("samvid-theme")).toBe("dark");
  expect(within(container).queryByRole("menu", { name: /sidebar actions|account/i })).not.toBeInTheDocument();
});

