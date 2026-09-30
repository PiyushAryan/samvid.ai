"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "@/lib/navigation";
import { useAuth } from "@/features/auth/auth-provider";
import { ApiError } from "@/lib/http-client";
import type { ContractListItem } from "@/features/contracts/types";
import { ContractMentionComposer } from "./contract-mention-composer";
import { createChatSession, getChatSession, streamChatMessage, updateChatContractScope, type ChatStreamHandlers } from "./api";
import type { ChatMessage, ChatSessionSummary } from "./types";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";

const compactButton = "secondary compact";

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function renderInlineMarkdown(value: string): ReactNode[] {
  const parts = value.split(/(\*\*[^*]+\*\*|`[^`]+`|\[S\d+\])/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{renderInlineMarkdown(part.slice(2, -2))}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (/^\[S\d+\]$/.test(part)) return null;
    return part;
  });
}

function ChatResponseContent({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const Heading = heading[1].length === 1 ? "h2" : "h3";
      blocks.push(<Heading key={`heading-${index}`}>{renderInlineMarkdown(heading[2])}</Heading>);
      index += 1;
      continue;
    }

    const plainSectionHeading = line.match(/^(facts|key finding|interpretation|suggested next steps|next steps)(?:\s*\([^)]*\))?$/i);
    if (plainSectionHeading) {
      blocks.push(<h2 key={`heading-${index}`}>{renderInlineMarkdown(line)}</h2>);
      index += 1;
      continue;
    }

    const unordered = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(isOrdered ? /^\d+[.)]\s+(.+)$/ : /^[-*]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const List = isOrdered ? "ol" : "ul";
      blocks.push(
        <List key={`list-${index}`}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderInlineMarkdown(item)}</li>)}
        </List>
      );
      continue;
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length) {
      const next = lines[index].trim();
      if (!next || /^(#{1,3})\s+|^[-*]\s+|^\d+[.)]\s+/.test(next)) break;
      paragraph.push(next);
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}>{renderInlineMarkdown(paragraph.join(" "))}</p>);
  }

  return <div className="ai-chat-markdown">{blocks}</div>;
}

function getWelcomeGreeting(name: string, now = new Date()): string {
  const hour = now.getHours();
  const greetings = hour >= 5 && hour < 12
    ? [`Good morning, ${name}`, `Ready when you are, ${name}`]
    : hour >= 12 && hour < 17
      ? [`Good afternoon, ${name}`, `Welcome back, ${name}`]
      : hour >= 17 && hour < 22
        ? [`Good evening, ${name}`, `Ask away, ${name}`]
        : [`Welcome back, ${name}`, `Ready when you are, ${name}`];

  return greetings[now.getDate() % greetings.length];
}

export function ChatsPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeChatId = searchParams.get("chat");
  const accountName = user?.name?.trim().split(/\s+/)[0] || "there";
  const welcomeGreeting = getWelcomeGreeting(accountName);
  const [liveConversation, setLiveConversation] = useState<{ sessionId: string; messages: ChatMessage[] } | null>(null);
  const [pendingMessages, setPendingMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [streamError, setStreamError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [draftScope, setDraftScope] = useState<ContractListItem | null>(null);
  const streamControllerRef = useRef<AbortController | null>(null);
  const sessionQuery = useQuery({
    queryKey: ["chat-session", activeChatId],
    queryFn: () => getChatSession(activeChatId!),
    enabled: Boolean(activeChatId)
  });
  const messages = pendingMessages.length > 0
    ? pendingMessages
    : liveConversation?.sessionId === activeChatId
      ? liveConversation.messages
      : sessionQuery.data?.messages || [];
  const isConversationView = Boolean(activeChatId || liveConversation || pendingMessages.length || isSending);
  const activeScope = activeChatId
    ? sessionQuery.data?.contract_id
      ? { id: sessionQuery.data.contract_id, title: sessionQuery.data.contract_title || "Untitled contract" }
      : null
    : draftScope
      ? { id: draftScope.id, title: draftScope.title }
      : null;

  const resetForNewChat = useCallback(() => {
    streamControllerRef.current?.abort();
    streamControllerRef.current = null;
    setLiveConversation(null);
    setPendingMessages([]);
    setStreamError("");
    setAnnouncement("");
    setIsSending(false);
    setDraftScope(null);
  }, []);

  useEffect(() => {
    window.addEventListener("samvid:new-chat", resetForNewChat);
    return () => window.removeEventListener("samvid:new-chat", resetForNewChat);
  }, [resetForNewChat]);

  useEffect(() => {
    if (activeChatId && liveConversation?.sessionId === activeChatId) return;
    streamControllerRef.current?.abort();
    streamControllerRef.current = null;
    setLiveConversation((current) => current?.sessionId === activeChatId ? current : null);
    setPendingMessages([]);
    setStreamError("");
    setAnnouncement("");
    setIsSending(false);
  // A new chat sets its live conversation before Next.js finishes updating the
  // URL. Only a URL change represents a user switching conversations; reacting
  // to the live session ID here would cancel that first response mid-start.
  }, [activeChatId]);

  useEffect(() => () => streamControllerRef.current?.abort(), []);

  const changeContractScope = async (contract: ContractListItem | null): Promise<boolean> => {
    if (!activeChatId) {
      setDraftScope(contract);
      return true;
    }
    try {
      const session = await updateChatContractScope(activeChatId, contract?.id ?? null);
      queryClient.setQueryData(["chat-session", activeChatId], (current: typeof session | undefined) => ({
        ...(current || session),
        ...session
      }));
      queryClient.setQueryData<ChatSessionSummary[]>(["chat-sessions"], (current = []) => current.map((item) => (
        item.id === session.id ? { ...item, ...session } : item
      )));
      return true;
    } catch {
      return false;
    }
  };

  const submitMessage = async (content: string): Promise<boolean> => {
    if (!content || isSending) return false;

    setIsSending(true);
    setStreamError("");
    setAnnouncement("Searching your contracts");
    let sessionId = activeChatId;
    const now = new Date().toISOString();
    const userMessage: ChatMessage = {
      id: `pending-user-${crypto.randomUUID()}`,
      role: "user",
      content,
      sources: [],
      created_at: now
    };
    const assistantId = `pending-assistant-${crypto.randomUUID()}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      sources: [],
      created_at: now
    };
    const baseMessages = sessionId === activeChatId ? messages : [];
    const nextMessages = [...baseMessages, userMessage, assistantMessage];
    if (!sessionId) setPendingMessages(nextMessages);

    try {
      if (!sessionId) {
        const session = draftScope
          ? await createChatSession(chatTitle(content), draftScope.id)
          : await createChatSession(chatTitle(content));
        sessionId = session.id;
        setDraftScope(null);
        queryClient.setQueryData(["chat-session", session.id], session);
        queryClient.setQueryData<ChatSessionSummary[]>(["chat-sessions"], (current = []) => [session, ...current]);
        navigate(`/chats?chat=${encodeURIComponent(session.id)}`, { replace: true });
      }

      setLiveConversation({ sessionId, messages: nextMessages });
      setPendingMessages([]);

      const controller = new AbortController();
      streamControllerRef.current = controller;
      const streamHandlers: ChatStreamHandlers = {
        onStatus: (status) => {
          setAnnouncement(status);
        },
        onDelta: (delta) => setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, (message) => ({
          ...message,
          content: message.content + delta
        }))),
        onSources: (sources) => setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, (message) => ({
          ...message,
          sources
        }))),
        onMessage: (message) => {
          setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, () => message));
        }
      };
      await streamChatMessage(sessionId, content, streamHandlers, controller.signal);
      setAnnouncement("Answer ready");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["chat-sessions"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session", sessionId] })
      ]);
      return true;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return false;
      setStreamError(chatErrorMessage(error));
      setPendingMessages([]);
      setLiveConversation((current) => current?.sessionId === sessionId
        ? { ...current, messages: current.messages.filter((message) => !message.id.startsWith("pending-assistant-")) }
        : current);
      setAnnouncement("Message was not completed");
      return false;
    } finally {
      streamControllerRef.current = null;
      setIsSending(false);
    }
  };

  return (
    <section className="ai-chat-page" aria-label="Contract chat" data-conversation={isConversationView}>
      <div className={cx("ai-chat-content", isConversationView && "ai-chat-content--conversation")}>
        {!isConversationView && (
          <header className="ai-chat-header">
            <h1>{welcomeGreeting}</h1>
            <p>find anything about your contracts</p>
          </header>
        )}

        {activeChatId && sessionQuery.isPending && !liveConversation ? (
          <div className="ai-chat-conversation-state" role="status">
            <Loader2 className="spin" size={18} aria-hidden="true" />
            <span>Loading conversation</span>
          </div>
        ) : activeChatId && sessionQuery.isError && !liveConversation ? (
          <div className="ai-chat-conversation-state ai-chat-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <strong>Conversation unavailable</strong>
            <span>{chatErrorMessage(sessionQuery.error)}</span>
            <button className={compactButton} type="button" onClick={() => void sessionQuery.refetch()}>Retry</button>
          </div>
        ) : messages.length > 0 ? (
          <div
            aria-busy={isSending}
            aria-label="Contract chat conversation"
            aria-live="polite"
            className="ai-chat-messages"
            role="log"
          >
            <div className="ai-chat-messages-content">
            {messages.map((message) => (
              <Message
                from={message.role}
                key={message.id}
                className={cx("ai-chat-message", `ai-chat-message-${message.role}`)}
              >
                <MessageContent className="ai-chat-message-content">
                  <span className="ai-chat-message-role">
                    {message.role === "user" ? "You" : "Samvid"}
                  </span>
                  {message.content ? (
                    message.role === "assistant"
                      ? <ChatResponseContent content={message.content} />
                      : <p>{message.content}</p>
                  ) : message.id.startsWith("pending-assistant-") ? (
                    <p>
                      {isSending && message.id.startsWith("pending-assistant-")
                        ? <Shimmer as="span" duration={1}>{announcement || "Searching your contracts..."}</Shimmer>
                        : "No response was returned."}
                    </p>
                  ) : null}
                </MessageContent>
              </Message>
            ))}
            </div>
          </div>
        ) : null}

        <ContractMentionComposer
          chatId={activeChatId}
          disabled={Boolean(activeChatId && sessionQuery.isPending)}
          error={streamError}
          isNewChat={!isConversationView}
          isSending={isSending}
          onScopeChange={changeContractScope}
          scope={activeScope}
          onSubmit={({ content }) => submitMessage(content)}
        />

        {!isConversationView && (
          <div className="ai-chat-suggestions" aria-label="Suggested questions">
            <p>Try asking</p>
            <Suggestions className="ai-chat-suggestions-list">
              {[
                "What changed in my latest contract?",
                "Which contracts renew in the next 90 days?",
                "Summarize the risks in this agreement."
              ].map((suggestion) => <Suggestion key={suggestion} onClick={() => window.dispatchEvent(new CustomEvent("samvid:chat-suggestion", { detail: suggestion }))} suggestion={suggestion} />)}
            </Suggestions>
          </div>
        )}
      </div>
    </section>
  );
}

function updateChatMessage(
  conversation: { sessionId: string; messages: ChatMessage[] } | null,
  sessionId: string,
  messageId: string,
  update: (message: ChatMessage) => ChatMessage
) {
  if (!conversation || conversation.sessionId !== sessionId) return conversation;
  return {
    ...conversation,
    messages: conversation.messages.map((message) => message.id === messageId ? update(message) : message)
  };
}

function chatTitle(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > 180 ? `${normalized.slice(0, 177)}...` : normalized;
}

function chatErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.payload.message) return error.payload.message;
    if (typeof error.payload.detail === "string") return error.payload.detail;
  }
  return error instanceof Error ? error.message : "Unable to reach Samvid AI. Please try again.";
}
