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
import * as api from "@/lib/api-client";
import * as contractApi from "@/features/contracts/api";
import * as chatApi from "@/features/chat/api";
import { TooltipProvider } from "@/components/ui/tooltip";
import { setTestUrl } from "@/test/mocks/next-navigation";
import type { ChatSession, ChatSessionSummary } from "@/features/chat/types";
import type { ContractDetail, ContractListItem, ContractReview } from "@/features/contracts/types";
import type { SigningRequest } from "@/features/signing/types";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    listChatSessions: vi.fn(),
    createChatSession: vi.fn(),
    getChatSession: vi.fn(),
    listContracts: vi.fn(),
    getContract: vi.fn(),
    getContractDocument: vi.fn(),
    deleteContract: vi.fn(),
    uploadContract: vi.fn(),
    getSlackIntegration: vi.fn(),
    beginSlackInstallation: vi.fn(),
    disconnectSlackInstallation: vi.fn(),
    streamChatMessage: vi.fn()
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

test("contract refresh rotates until updated API data arrives", async () => {
  setTestUrl("/contracts");
  render(<QueryProvider><ContractsPage /></QueryProvider>);

  const refreshButton = screen.getByRole("button", { name: "Refresh contracts" });
  await waitFor(() => expect(refreshButton).not.toBeDisabled());

  let resolveRefresh!: (contracts: ContractListItem[]) => void;
  vi.mocked(contractApi.listContracts).mockReturnValueOnce(new Promise((resolve) => {
    resolveRefresh = resolve;
  }));

  fireEvent.click(refreshButton);

  await waitFor(() => {
    expect(contractApi.listContracts).toHaveBeenLastCalledWith({ search: "", reviewStatus: "", signingStatus: "" });
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

test("contract upload distinguishes transfer from review startup and confirms success", async () => {
  let finishUpload!: (result: api.ContractUploadResult) => void;
  vi.mocked(contractApi.uploadContract).mockImplementationOnce((_file, onProgress) => {
    onProgress({ percentage: 100, stage: "starting_review" });
    return new Promise((resolve) => {
      finishUpload = resolve;
    });
  });

  setTestUrl("/contracts");
  render(<QueryProvider><ContractsPage /></QueryProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));

  const dialog = screen.getByRole("dialog", { name: "Upload contract" });
  const file = new File(["contract"], "Dawnify agreement.pdf", { type: "application/pdf" });
  fireEvent.change(within(dialog).getByLabelText("Choose contract file"), { target: { files: [file] } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Process" }));

  expect(await within(dialog).findByText("Upload complete. Starting contract review…")).toBeInTheDocument();
  expect(within(dialog).getByRole("progressbar")).not.toHaveAttribute("value");
  expect(within(dialog).getByRole("button", { name: "Starting review" })).toBeDisabled();
  expect(contractApi.uploadContract).toHaveBeenCalledWith(file, expect.any(Function), expect.any(AbortSignal));

  finishUpload({
    contract_id: "contract-uploaded",
    contract_version_id: "version-uploaded",
    status: "queued",
    message: "Contract accepted and queued for review."
  });

  expect(await within(dialog).findByText("Contract received")).toBeInTheDocument();
  expect(within(dialog).getByText("Contract accepted and queued for review.")).toBeInTheDocument();
  expect(within(dialog).getByText("Dawnify agreement.pdf")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Done" }));
  expect(screen.queryByRole("dialog", { name: "Upload contract" })).not.toBeInTheDocument();
});

test("contract upload exits loading state after a timeout and remains retryable", async () => {
  vi.mocked(contractApi.uploadContract).mockRejectedValueOnce(new api.ApiError(408, {
    code: "upload_timeout",
    message: "The file was uploaded, but starting its review took too long. Refresh Contracts before trying again."
  }));

  setTestUrl("/contracts");
  render(<QueryProvider><ContractsPage /></QueryProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));

  const dialog = screen.getByRole("dialog", { name: "Upload contract" });
  const file = new File(["contract"], "agreement.pdf", { type: "application/pdf" });
  fireEvent.change(within(dialog).getByLabelText("Choose contract file"), { target: { files: [file] } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Process" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("starting its review took too long");
  expect(within(dialog).queryByRole("progressbar")).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Try again" })).toBeEnabled();
  expect(within(dialog).getByText("agreement.pdf")).toBeInTheDocument();
});

test("closing the upload dialog aborts the in-flight upload", async () => {
  let uploadSignal: AbortSignal | undefined;
  vi.mocked(contractApi.uploadContract).mockImplementationOnce((_file, _onProgress, signal) => {
    uploadSignal = signal;
    return new Promise(() => undefined);
  });

  setTestUrl("/contracts");
  render(<QueryProvider><ContractsPage /></QueryProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));

  const dialog = screen.getByRole("dialog", { name: "Upload contract" });
  const file = new File(["contract"], "agreement.pdf", { type: "application/pdf" });
  fireEvent.change(within(dialog).getByLabelText("Choose contract file"), { target: { files: [file] } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Process" }));

  await waitFor(() => expect(uploadSignal).toBeInstanceOf(AbortSignal));
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

  expect(uploadSignal?.aborted).toBe(true);
  expect(screen.queryByRole("dialog", { name: "Upload contract" })).not.toBeInTheDocument();
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

  await waitFor(() => expect(contractApi.deleteContract).toHaveBeenCalledWith("contract-delete"));
  expect(window.location.pathname).toBe("/contracts");
});

test("contract loading state exposes one accessible status and hides its placeholders", () => {
  const { container } = render(<ContractsTableSkeleton />);

  expect(within(container).getByRole("status")).toHaveTextContent("Loading contracts");
  expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(32);
  expect(container.querySelector(".contracts-skeleton")).toHaveAttribute("aria-hidden", "true");
});

test("risks tab renders evidence-grounded risks", () => {
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

  render(<RisksTab review={review} />);

  expect(screen.queryByText("Risk register")).not.toBeInTheDocument();
  expect(screen.getByText("Unlimited liability")).toBeInTheDocument();
  expect(screen.getByText("Page 2")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "View evidence from page 2: liability shall be unlimited" })).toBeInTheDocument();
  expect(screen.getByText("95% confidence")).toBeInTheDocument();
});
