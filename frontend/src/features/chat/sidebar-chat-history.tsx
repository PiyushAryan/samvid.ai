"use client";

import { SquarePen } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { listChatSessions } from "./api";

export function SidebarChatHistory({
  activeChatId,
  onSelect
}: {
  activeChatId: string | null;
  onSelect: (chatId: string | null) => void;
}) {
  const sessionsQuery = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: listChatSessions
  });

  return (
    <section className="sidebar-chat-section" aria-labelledby="sidebar-chat-history-title">
      <button
        className="sidebar-new-chat"
        type="button"
        onClick={() => {
          window.dispatchEvent(new Event("samvid:new-chat"));
          onSelect(null);
        }}
      >
        <SquarePen size={16} aria-hidden="true" />
        <span>New chat</span>
      </button>
      <h2 id="sidebar-chat-history-title" className="sr-only">Chat history</h2>
      {sessionsQuery.isPending ? (
        <div className="sidebar-chat-loading" role="status" aria-label="Loading chat history">
          {[0, 1, 2].map((item) => <Skeleton key={item} className="sidebar-chat-skeleton" />)}
        </div>
      ) : sessionsQuery.isError ? (
        <div className="sidebar-chat-state" role="alert">
          <span>History unavailable</span>
          <button type="button" onClick={() => void sessionsQuery.refetch()}>Retry</button>
        </div>
      ) : sessionsQuery.data.length === 0 ? (
        <p className="sidebar-chat-empty">No conversations yet</p>
      ) : (
        <ul className="sidebar-chat-list">
          {sessionsQuery.data.map((session) => (
            <li key={session.id}>
              <button
                type="button"
                title={session.title}
                aria-current={activeChatId === session.id ? "page" : undefined}
                onClick={() => onSelect(session.id)}
              >
                {session.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

