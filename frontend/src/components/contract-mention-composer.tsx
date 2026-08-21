"use client";

import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $getRoot, $getSelection, COMMAND_PRIORITY_HIGH, KEY_DOWN_COMMAND } from "lexical";
import { FileText, Plus, X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Drawer } from "vaul";

import { listContracts } from "@/api";
import { PromptInput, PromptInputFooter, PromptInputSubmit } from "@/components/ai-elements/prompt-input";
import { useQuery } from "@tanstack/react-query";
import type { ContractListItem } from "@/types";

export type ContractMentionSubmission = {
  content: string;
};

export type ChatContractScope = { id: string; title: string };

type ContractMentionComposerProps = {
  disabled?: boolean;
  error?: string;
  isSending: boolean;
  isNewChat: boolean;
  chatId: string | null;
  scope: ChatContractScope | null;
  onScopeChange: (contract: ContractListItem | null) => Promise<boolean>;
  onSubmit: (submission: ContractMentionSubmission) => Promise<boolean>;
};

type EditorHandle = {
  clear: () => void;
  insertMention: (value: string) => void;
};

const editorTheme = {
  paragraph: "contract-mention-editor-paragraph"
};

const ContractEditorController = forwardRef<EditorHandle, {
  disabled: boolean;
  onChange: (value: string) => void;
  onTrigger: (trigger: "@" | "/") => void;
}>(({ disabled, onChange, onTrigger }, ref) => {
  const [editor] = useLexicalComposerContext();

  useImperativeHandle(ref, () => ({
    clear: () => editor.update(() => $getRoot().clear()),
    insertMention: (value) => editor.update(() => {
      let selection = $getSelection();
      if (!selection) {
        $getRoot().selectEnd();
        selection = $getSelection();
      }
      selection?.insertText(value);
    })
  }), [editor]);

  useEffect(() => editor.registerCommand(
    KEY_DOWN_COMMAND,
    (event) => {
      if (disabled || event.metaKey || event.ctrlKey || event.altKey || (event.key !== "@" && event.key !== "/")) return false;
      event.preventDefault();
      onTrigger(event.key);
      return true;
    },
    COMMAND_PRIORITY_HIGH
  ), [disabled, editor, onTrigger]);

  return <OnChangePlugin onChange={(editorState) => editorState.read(() => onChange($getRoot().getTextContent().trim()))} />;
});

ContractEditorController.displayName = "ContractEditorController";

export function ContractMentionComposer({ disabled = false, error, isSending, isNewChat, chatId, scope, onScopeChange, onSubmit }: ContractMentionComposerProps) {
  const editorRef = useRef<EditorHandle>(null);
  const [drawerContainer, setDrawerContainer] = useState<HTMLDivElement | null>(null);
  const [content, setContent] = useState("");
  const [debouncedContractQuery, setDebouncedContractQuery] = useState("");
  const [optimisticScope, setOptimisticScope] = useState<ContractListItem | null | undefined>(undefined);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [highlightedContractIndex, setHighlightedContractIndex] = useState(0);
  const [scopeError, setScopeError] = useState("");
  const [isUpdatingScope, setIsUpdatingScope] = useState(false);
  const contractsQuery = useQuery({
    queryKey: ["contract-mention-options"],
    queryFn: () => listContracts({}),
    enabled: pickerOpen
  });
  const initialConfig = useMemo(() => ({
    namespace: "SamvidContractMentionComposer",
    theme: editorTheme,
    onError: (error: Error) => { throw error; }
  }), []);

  const openPicker = (_trigger: "@" | "/") => {
    setPickerOpen(true);
  };

  useEffect(() => {
    if (!pickerOpen) {
      setDebouncedContractQuery("");
      return;
    }
    const timeout = window.setTimeout(() => setDebouncedContractQuery(content.trim().toLocaleLowerCase()), 180);
    return () => window.clearTimeout(timeout);
  }, [content, pickerOpen]);

  const filteredContracts = useMemo(() => {
    const contracts = contractsQuery.data ?? [];
    if (!debouncedContractQuery) return contracts;
    return contracts.filter((contract) => contract.title.toLocaleLowerCase().includes(debouncedContractQuery));
  }, [contractsQuery.data, debouncedContractQuery]);

  useEffect(() => {
    setHighlightedContractIndex(0);
  }, [debouncedContractQuery, pickerOpen]);

  useEffect(() => {
    setHighlightedContractIndex((current) => Math.min(current, Math.max(filteredContracts.length - 1, 0)));
  }, [filteredContracts.length]);

  const displayedScope = optimisticScope === undefined
    ? scope
    : optimisticScope && { id: optimisticScope.id, title: optimisticScope.title };

  useEffect(() => {
    if (optimisticScope === undefined) return;
    if ((optimisticScope === null && scope === null) || optimisticScope?.id === scope?.id) {
      setOptimisticScope(undefined);
    }
  }, [optimisticScope, scope]);

  useEffect(() => {
    const insertSuggestion = (event: Event) => {
      const value = (event as CustomEvent<string>).detail;
      if (value) editorRef.current?.insertMention(value);
    };
    window.addEventListener("samvid:chat-suggestion", insertSuggestion);
    return () => window.removeEventListener("samvid:chat-suggestion", insertSuggestion);
  }, []);

  useEffect(() => {
    const reset = () => {
      setContent("");
      setScopeError("");
      editorRef.current?.clear();
    };
    window.addEventListener("samvid:new-chat", reset);
    return () => window.removeEventListener("samvid:new-chat", reset);
  }, []);

  useEffect(() => {
    setContent("");
    setScopeError("");
    setOptimisticScope(undefined);
    editorRef.current?.clear();
  }, [chatId]);

  const changeScope = async (contract: ContractListItem | null) => {
    if (disabled || isSending || isUpdatingScope) return;
    setScopeError("");
    setOptimisticScope(contract);
    setPickerOpen(false);
    if (contract) {
      setContent("");
      editorRef.current?.clear();
    }
    setIsUpdatingScope(true);
    let updated = false;
    try {
      updated = await onScopeChange(contract);
    } catch {
      updated = false;
    } finally {
      setIsUpdatingScope(false);
    }
    if (!updated) {
      setOptimisticScope(undefined);
      setScopeError("Contract scope could not be updated. Try again.");
      return;
    }
  };

  const handlePickerKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!pickerOpen || !filteredContracts.length) {
      if (pickerOpen && event.key === "Escape") {
        event.preventDefault();
        setPickerOpen(false);
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      event.stopPropagation();
      setHighlightedContractIndex((current) => (current + 1) % filteredContracts.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      event.stopPropagation();
      setHighlightedContractIndex((current) => (current - 1 + filteredContracts.length) % filteredContracts.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      void changeScope(filteredContracts[highlightedContractIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setPickerOpen(false);
    }
  };

  const submit = async () => {
    if (!content || disabled || isSending || isUpdatingScope) return;
    const submitted = await onSubmit({ content });
    if (submitted) editorRef.current?.clear();
  };

  const isIdleNewChat = isNewChat && !content && !displayedScope && !pickerOpen && !isSending && !error && !scopeError;

  return (
    <div onKeyDownCapture={handlePickerKeyDown} ref={setDrawerContainer} className={`contract-mention-composer-anchor${isNewChat ? " contract-mention-composer-anchor--new-chat" : ""}${pickerOpen ? " contract-mention-composer-anchor--picker-open" : ""}`}>
      <PromptInput className={`ai-chat-composer contract-mention-composer${isIdleNewChat ? " contract-mention-composer--new-chat-idle" : ""}`} onSubmit={() => void submit()}>
        <div className="contract-mention-main">
          <button
            aria-label={displayedScope ? "Change contract scope" : "Choose a contract scope"}
            className="contract-mention-add"
            disabled={disabled || isSending || isUpdatingScope}
            onClick={() => openPicker("@")}
            type="button"
          >
            <Plus size={16} aria-hidden="true" />
          </button>
          <div className={`contract-mention-editor-shell${displayedScope ? " contract-mention-editor-shell--scoped" : ""}`}>
            {displayedScope && (
              <span className="contract-mention-scope">
                <FileText size={13} aria-hidden="true" />
                <span>{displayedScope.title}</span>
                <button aria-label={`Clear ${displayedScope.title} contract scope`} disabled={disabled || isSending || isUpdatingScope} onClick={() => void changeScope(null)} type="button">
                  <X size={13} aria-hidden="true" />
                </button>
              </span>
            )}
            <LexicalComposer initialConfig={initialConfig}>
              <RichTextPlugin
                contentEditable={<ContentEditable aria-label="Ask about a contract" aria-placeholder="Ask about your contracts… Type @ or / to choose one." className="contract-mention-editor" contentEditable={!disabled && !isSending && !isUpdatingScope} onInput={(event) => setContent(event.currentTarget.textContent?.trim() || "")} placeholder={<span />} />}
                ErrorBoundary={LexicalErrorBoundary}
                placeholder={<span className="contract-mention-placeholder">Ask about your contracts… Type <kbd>@</kbd> or <kbd>/</kbd> to choose one.</span>}
              />
              <HistoryPlugin />
              <ContractEditorController disabled={disabled || isSending || isUpdatingScope} onChange={setContent} onTrigger={openPicker} ref={editorRef} />
            </LexicalComposer>
          </div>
        </div>
        <PromptInputFooter className="ai-chat-composer-actions contract-mention-footer">
          <PromptInputSubmit aria-label="Send message" className="ai-chat-send-button" disabled={!content || disabled || isSending || isUpdatingScope} status={isSending ? "streaming" : "ready"} />
        </PromptInputFooter>
        {(error || scopeError) && <p className="ai-chat-stream-error" role="alert">{scopeError || error}</p>}
      </PromptInput>
      <Drawer.Root container={drawerContainer} direction={isNewChat ? "bottom" : "top"} open={pickerOpen} onOpenChange={setPickerOpen}>
        <Drawer.Portal container={drawerContainer}>
          <Drawer.Overlay className="contract-picker-overlay" />
          <Drawer.Content aria-labelledby="contract-picker-title" className="contract-picker-drawer">
            <div className="contract-picker-content">
              <div className="contract-picker-intro">
                <span className="contract-picker-intro-icon" aria-hidden="true"><FileText size={15} /></span>
                <div>
                  <Drawer.Title id="contract-picker-title">Choose one contract for Samvid to use in this chat.</Drawer.Title>
                </div>
              </div>
              <div className="contract-picker-list" role="listbox" aria-label="Contracts">
                {contractsQuery.isPending ? <p>Loading contracts…</p> : contractsQuery.isError ? <p>Contracts could not be loaded. Try again.</p> : filteredContracts.length ? filteredContracts.map((contract, index) => (
                  <button aria-selected={index === highlightedContractIndex} className={index === highlightedContractIndex ? "contract-picker-option--highlighted" : undefined} disabled={isUpdatingScope} key={contract.id} onClick={() => void changeScope(contract)} onMouseEnter={() => setHighlightedContractIndex(index)} role="option" type="button">
                    <span>{contract.title || "Untitled contract"}</span>
                  </button>
                )) : <p>No contracts match this search.</p>}
              </div>
            </div>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
    </div>
  );
}
