export type ChatMessageRole = "user" | "assistant";

export interface ChatSource {
  id?: string;
  contract_id: string;
  contract_title: string;
  page_number: number | null;
  excerpt: string | null;
  relevance?: number | null;
}

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  sources: ChatSource[];
  created_at: string;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  contract_id: string | null;
  contract_title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatSession extends ChatSessionSummary {
  messages: ChatMessage[];
}

export type ChatStreamEvent =
  | { type: "message.delta"; delta: string }
  | { type: "message.sources"; sources: ChatSource[] }
  | { type: "message.completed"; message: ChatMessage }
  | { type: "error"; code?: string; message: string };
