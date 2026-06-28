"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { logout } from "@/features/auth/api";
import type { Asset, ChatMessage, ChatModel, Conversation, StreamEvent } from "@/types/api";
import {
  createConversationApi,
  deleteConversationApi,
  getConversationMessages,
  listAssets,
  listChatModels,
  listConversations,
  renameConversationApi,
  updateConversationModelApi,
  uploadAsset,
} from "@/features/chat/api";
import { ChatComposer } from "@/features/chat/components/ChatComposer";
import { ConversationRail } from "@/features/chat/components/ConversationRail";
import { MessageList } from "@/features/chat/components/MessageList";
import { SourceModal } from "@/features/chat/components/SourceModal";
import { ToolsSidebar } from "@/features/chat/components/ToolsSidebar";
import { assetIsSelectable } from "@/features/chat/utils/assets";
import { traceLabel } from "@/features/chat/utils/stream";
import styles from "@/app/page.module.css";

type ChatAppProps = {
  user: {
    label: string;
    isAdmin: boolean;
  };
};

export function ChatApp({ user }: ChatAppProps) {
  const [models, setModels] = useState<ChatModel[]>([]);
  const [selectedModel, setSelectedModel] = useState("ollama|gemma3:12b");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set());
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const [sourceModalOpen, setSourceModalOpen] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [status, setStatus] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) || null,
    [activeConversationId, conversations],
  );

  const selectedAssets = useMemo(
    () => assets.filter((asset) => selectedAssetIds.has(asset.id)),
    [assets, selectedAssetIds],
  );

  async function bootstrap() {
    try {
      await Promise.all([loadModels(), loadConversations(), loadAssets()]);
    } catch {
      setStatus("خطا در دریافت اطلاعات اولیه.");
    }
  }

  async function loadModels() {
    const data = await listChatModels();
    setModels(data.models || []);
    const preferred = (data.models || []).find((model) => model.default && model.enabled) || (data.models || []).find((model) => model.enabled);
    if (preferred) setSelectedModel(`${preferred.provider}|${preferred.model}`);
  }

  async function loadConversations() {
    const data = await listConversations();
    const rows = data.conversations || [];
    setConversations(rows);
    if (!activeConversationId && rows[0]) {
      await selectConversation(rows[0].id);
    }
  }

  async function loadAssets() {
    const data = await listAssets();
    const rows = data.assets || [];
    setAssets(rows);
    setSelectedAssetIds((current) => new Set([...current].filter((id) => rows.some((asset) => asset.id === id && assetIsSelectable(asset)))));
  }

  async function selectConversation(id: string) {
    setActiveConversationId(id);
    const data = await getConversationMessages(id);
    upsertConversation({ ...data.conversation, messages: data.messages || [] });
    const value = data.conversation.chat_provider && data.conversation.chat_model
      ? `${data.conversation.chat_provider}|${data.conversation.chat_model}`
      : null;
    if (value) setSelectedModel(value);
  }

  async function createConversation() {
    const [provider, ...modelParts] = selectedModel.split("|");
    const data = await createConversationApi(provider, modelParts.join("|"));
    const created = { ...data.conversation, messages: [] };
    upsertConversation(created);
    setActiveConversationId(created.id);
    return created.id;
  }

  function upsertConversation(conversation: Conversation) {
    setConversations((current) => {
      const merged = current.some((item) => item.id === conversation.id)
        ? current.map((item) => item.id === conversation.id ? { ...item, ...conversation, messages: conversation.messages ?? item.messages } : item)
        : [conversation, ...current];
      return merged.sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime());
    });
  }

  function upsertMessage(conversationId: string, message: ChatMessage) {
    setConversations((current) => current.map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      const messages = conversation.messages || [];
      const nextMessages = messages.some((item) => item.id === message.id)
        ? messages.map((item) => item.id === message.id ? { ...item, ...message } : item)
        : [...messages, message];
      return { ...conversation, messages: nextMessages };
    }));
  }

  async function updateConversationModel(value: string) {
    setSelectedModel(value);
    if (!activeConversationId) return;
    const [provider, ...modelParts] = value.split("|");
    const data = await updateConversationModelApi(activeConversationId, provider, modelParts.join("|"));
    upsertConversation(data.conversation);
  }

  async function logoutUser() {
    setIsLoggingOut(true);
    setStatus("");
    try {
      await logout();
      window.location.href = "/login";
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خروج ناموفق بود.");
      setIsLoggingOut(false);
    }
  }

  function toggleTheme() {
    const root = document.documentElement;
    const current = root.getAttribute("data-theme") === "light" ? "light" : "dark";
    const next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
  }

  async function renameConversation(conversation: Conversation) {
    const nextTitle = window.prompt("نام جدید گفتگو", conversation.title)?.trim();
    if (!nextTitle || nextTitle === conversation.title) return;
    try {
      const data = await renameConversationApi(conversation.id, nextTitle);
      upsertConversation(data.conversation);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در تغییر نام گفتگو");
    }
  }

  async function deleteConversation(conversation: Conversation) {
    const confirmed = window.confirm(`گفتگوی «${conversation.title}» حذف شود؟`);
    if (!confirmed) return;
    try {
      await deleteConversationApi(conversation.id);
      const remaining = conversations.filter((item) => item.id !== conversation.id);
      setConversations(remaining);
      if (activeConversationId === conversation.id) {
        const nextConversation = remaining[0];
        if (nextConversation) await selectConversation(nextConversation.id);
        else setActiveConversationId(null);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در حذف گفتگو");
    }
  }

  async function submitQuestion(event?: FormEvent) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || isSending) return;
    setIsSending(true);
    setQuestion("");
    let conversationId = activeConversationId || await createConversation();
    const [provider, ...modelParts] = selectedModel.split("|");
    let assistantId: string | null = null;
    let answer = "";

    try {
      const res = await fetch("/api/ask/stream", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
          asset_ids: [...selectedAssetIds],
          conversation_id: conversationId,
          chat_provider: provider,
          chat_model: modelParts.join("|"),
        }),
      });
      if (!res.ok || !res.body) throw new Error("خطا در ارسال درخواست");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const handleEvent = (streamEvent: StreamEvent) => {
        if (streamEvent.type === "conversation") {
          conversationId = streamEvent.conversation.id;
          assistantId = streamEvent.assistant_message.id;
          upsertConversation(streamEvent.conversation);
          upsertMessage(conversationId, streamEvent.user_message);
          upsertMessage(conversationId, { ...streamEvent.assistant_message, status: "streaming" });
          setActiveConversationId(conversationId);
        } else if (streamEvent.type === "trace" && assistantId && !answer) {
          upsertMessage(conversationId, { id: assistantId, role: "assistant", content: "", status: "streaming", stream_status: `${traceLabel(streamEvent)}...` });
        } else if (streamEvent.type === "token" && assistantId) {
          answer += streamEvent.delta || "";
          upsertMessage(conversationId, { id: assistantId, role: "assistant", content: answer, status: "streaming", stream_status: null });
        } else if (streamEvent.type === "final" && assistantId) {
          answer = answer || streamEvent.answer || "";
          upsertMessage(conversationId, { id: assistantId, role: "assistant", content: answer, sources: streamEvent.sources || [], status: "complete", stream_status: null });
        } else if (streamEvent.type === "error" && assistantId) {
          upsertMessage(conversationId, { id: assistantId, role: "assistant", content: streamEvent.error || "خطا در تولید پاسخ.", status: "error" });
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.trim()) handleEvent(JSON.parse(line) as StreamEvent);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) handleEvent(JSON.parse(buffer) as StreamEvent);
    } catch (error) {
      const message = error instanceof Error ? error.message : "خطا در ارتباط با سرور";
      if (assistantId) upsertMessage(conversationId, { id: assistantId, role: "assistant", content: message, status: "error" });
      else setStatus(message);
    } finally {
      setIsSending(false);
    }
  }

  async function uploadFile(file: File) {
    setStatus("در حال آپلود...");
    const data = await uploadAsset(file);
    const created = data.created?.[0];
    if (!created) {
      setStatus(data.rejected?.[0]?.error || "خطا در آپلود فایل");
      return;
    }
    setStatus("فایل دریافت شد و در حال پردازش است.");
    await loadAssets();
  }

  function toggleAsset(asset: Asset, checked: boolean) {
    if (asset.category !== "text" || asset.status !== "scanned") return;
    setSelectedAssetIds((current) => {
      const next = new Set(current);
      if (checked) next.add(asset.id);
      else next.delete(asset.id);
      return next;
    });
  }

  useEffect(() => {
    void bootstrap();
    // The initial bootstrap intentionally runs once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const messages = activeConversation?.messages || [];

  return (
    <main className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.brand}><AppIcon name="file" /> دستیار اسناد</div>
        <div className={styles.accountArea}>
          <Link className={styles.user} href="/profile">
            <AppIcon name="user" />
            <span>{user.label}</span>
          </Link>
          <button className={styles.themeButton} onClick={toggleTheme} type="button" title="تغییر تم">
            <AppIcon name="theme" />
          </button>
          <button className={styles.logoutButton} disabled={isLoggingOut} onClick={() => void logoutUser()} type="button">
            {isLoggingOut ? "در حال خروج..." : "خروج"}
          </button>
        </div>
      </header>

      <div className={styles.layout}>
        <ToolsSidebar />

        <section className={styles.workspace}>
          <div className={styles.workspaceHead}>
            <span className={styles.headIcon}><AppIcon name="chat" /></span>
            <div>
              <h1>چت هوشمند</h1>
              <p>بدون منبع برای چت آزاد، یا با انتخاب اسناد برای پاسخ مستند.</p>
              <span className={styles.mode}>{selectedAssets.length ? `حالت مستند: ${selectedAssets.length.toLocaleString("fa-IR")} منبع` : "حالت چت آزاد"}</span>
            </div>
          </div>

          <MessageList messages={messages} />

          <ChatComposer
            question={question}
            selectedModel={selectedModel}
            models={models}
            selectedSourceCount={selectedAssets.length}
            sourceMenuOpen={sourceMenuOpen}
            isSending={isSending}
            textareaRef={textareaRef}
            onQuestionChange={setQuestion}
            onSubmit={(event) => void submitQuestion(event)}
            onToggleSourceMenu={() => setSourceMenuOpen((value) => !value)}
            onOpenSourceModal={() => { setSourceMenuOpen(false); setSourceModalOpen(true); void loadAssets(); }}
            onModelChange={(value) => void updateConversationModel(value)}
          />
          {status && <div className={styles.status}>{status}</div>}
        </section>

        <ConversationRail
          conversations={conversations}
          activeConversationId={activeConversationId}
          onCreateConversation={() => void createConversation()}
          onSelectConversation={(id) => void selectConversation(id)}
          onRenameConversation={(conversation) => void renameConversation(conversation)}
          onDeleteConversation={(conversation) => void deleteConversation(conversation)}
        />
      </div>

      {sourceModalOpen && (
        <SourceModal
          assets={assets}
          selectedAssetIds={selectedAssetIds}
          selectedAssets={selectedAssets}
          sourceQuery={sourceQuery}
          onClose={() => setSourceModalOpen(false)}
          onUploadClick={() => fileInputRef.current?.click()}
          onClearSelection={() => setSelectedAssetIds(new Set())}
          onQueryChange={setSourceQuery}
          onToggleAsset={toggleAsset}
        />
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.pdf,.docx"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void uploadFile(file);
          event.currentTarget.value = "";
        }}
      />
    </main>
  );
}
