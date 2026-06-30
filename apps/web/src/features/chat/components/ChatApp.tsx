"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AppIcon } from "@/components/AppIcon";
import { logout } from "@/features/auth/api";
import type { Asset, ChatMessage, ChatModel, ChatTool, Conversation, GeneratedOutput, SelectedTool, StreamEvent } from "@/types/api";
import {
  createConversationApi,
  deleteConversationApi,
  getConversationMessages,
  getGeneratedOutput,
  listAssets,
  listChatModels,
  listConversations,
  listTools,
  renameConversationApi,
  updateConversationModelApi,
  uploadAsset,
} from "@/features/chat/api";
import { ChatComposer } from "@/features/chat/components/ChatComposer";
import { ConversationRail } from "@/features/chat/components/ConversationRail";
import { MessageList } from "@/features/chat/components/MessageList";
import { OutputCanvas } from "@/features/chat/components/OutputCanvas";
import { SourceModal } from "@/features/chat/components/SourceModal";
import { ToolsSidebar } from "@/features/chat/components/ToolsSidebar";
import { ToolPickerModal } from "@/features/chat/components/ToolPickerModal";
import { assetIsSelectable } from "@/features/chat/utils/assets";
import { traceLabel } from "@/features/chat/utils/stream";
import styles from "@/app/page.module.css";

type ChatAppProps = {
  user: {
    label: string;
    isAdmin: boolean;
  };
};

const FALLBACK_MODEL = "ollama|gemma3:12b";

export function ChatApp({ user }: ChatAppProps) {
  const [models, setModels] = useState<ChatModel[]>([]);
  const [tools, setTools] = useState<ChatTool[]>([]);
  const [defaultModel, setDefaultModel] = useState(FALLBACK_MODEL);
  const [selectedModel, setSelectedModel] = useState(FALLBACK_MODEL);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set());
  const [selectedTool, setSelectedTool] = useState<SelectedTool | null>(null);
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const [sourceModalOpen, setSourceModalOpen] = useState(false);
  const [toolPickerOpen, setToolPickerOpen] = useState(false);
  const [activeOutput, setActiveOutput] = useState<GeneratedOutput | null>(null);
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

  const activeAssetIds = useMemo(
    () => selectedTool ? new Set(selectedTool.assetIds) : selectedAssetIds,
    [selectedAssetIds, selectedTool],
  );

  const activeAssets = useMemo(
    () => assets.filter((asset) => activeAssetIds.has(asset.id)),
    [activeAssetIds, assets],
  );

  async function bootstrap() {
    try {
      await loadModels();
      await Promise.all([loadTools(), loadConversations(), loadAssets()]);
    } catch {
      setStatus("خطا در دریافت اطلاعات اولیه.");
    }
  }

  async function loadModels() {
    const data = await listChatModels();
    setModels(data.models || []);
    const preferred = (data.models || []).find((model) => model.default && model.enabled) || (data.models || []).find((model) => model.enabled);
    if (preferred) {
      const nextDefault = `${preferred.provider}|${preferred.model}`;
      setDefaultModel(nextDefault);
      setSelectedModel(nextDefault);
    }
  }

  async function loadTools() {
    const data = await listTools();
    setTools(data.tools || []);
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

  function resetTransientChatState() {
    setQuestion("");
    setSelectedAssetIds(new Set());
    setSelectedTool(null);
    setSourceMenuOpen(false);
    setSourceModalOpen(false);
    setToolPickerOpen(false);
    setActiveOutput(null);
    setSourceQuery("");
    setStatus("");
  }

  function startNewConversation() {
    setActiveConversationId(null);
    resetTransientChatState();
    setSelectedModel(defaultModel);
  }

  async function selectConversation(id: string) {
    resetTransientChatState();
    setActiveConversationId(id);
    const data = await getConversationMessages(id);
    upsertConversation({ ...data.conversation, messages: data.messages || [] });
    const value = data.conversation.chat_provider && data.conversation.chat_model
      ? `${data.conversation.chat_provider}|${data.conversation.chat_model}`
      : null;
    setSelectedModel(value || defaultModel);
  }

  async function createConversation(modelValue = selectedModel) {
    const [provider, ...modelParts] = modelValue.split("|");
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
        else startNewConversation();
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در حذف گفتگو");
    }
  }

  async function openOutput(message: ChatMessage) {
    if (message.generated_output) {
      setActiveOutput(message.generated_output);
      return;
    }
    if (!message.generated_output_id) return;
    try {
      const data = await getGeneratedOutput(message.generated_output_id);
      setActiveOutput(data.output);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "خطا در باز کردن خروجی");
    }
  }

  async function submitQuestion(event?: FormEvent) {
    event?.preventDefault();
    const text = question.trim();
    if ((!text && !selectedTool) || isSending) return;
    setIsSending(true);
    setQuestion("");
    const modelValue = selectedModel;
    let conversationId = activeConversationId || await createConversation(modelValue);
    const [provider, ...modelParts] = modelValue.split("|");
    let assistantId: string | null = null;
    let answer = "";

    try {
      const res = await fetch("/api/ask/stream", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
          asset_ids: [...activeAssetIds],
          tool_id: selectedTool?.tool.id,
          tool_params: selectedTool?.params,
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
          if (streamEvent.generated_output) setActiveOutput(streamEvent.generated_output);
          upsertMessage(conversationId, {
            id: assistantId,
            role: "assistant",
            content: answer,
            sources: streamEvent.sources || [],
            status: "complete",
            stream_status: null,
            generated_output_id: streamEvent.generated_output?.id,
            generated_output: streamEvent.generated_output || null,
          });
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
              <span className={styles.mode}>{activeAssets.length ? `حالت مستند: ${activeAssets.length.toLocaleString("fa-IR")} منبع` : "حالت چت آزاد"}</span>
            </div>
          </div>

          <MessageList messages={messages} onOpenOutput={(message) => void openOutput(message)} />

          <ChatComposer
            question={question}
            selectedModel={selectedModel}
            models={models}
            selectedSourceCount={activeAssets.length}
            selectedTool={selectedTool}
            sourceMenuOpen={sourceMenuOpen}
            isSending={isSending}
            textareaRef={textareaRef}
            onQuestionChange={setQuestion}
            onSubmit={(event) => void submitQuestion(event)}
            onToggleSourceMenu={() => setSourceMenuOpen((value) => !value)}
            onOpenSourceModal={() => { setSourceMenuOpen(false); setSourceModalOpen(true); void loadAssets(); }}
            onOpenToolPicker={() => { setSourceMenuOpen(false); setToolPickerOpen(true); }}
            onClearTool={() => setSelectedTool(null)}
            onModelChange={(value) => void updateConversationModel(value)}
          />
          {status && <div className={styles.status}>{status}</div>}
        </section>

        <ConversationRail
          conversations={conversations}
          activeConversationId={activeConversationId}
          onCreateConversation={startNewConversation}
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

      {toolPickerOpen && (
        <ToolPickerModal
          tools={tools}
          assets={assets}
          selectedTool={selectedTool}
          selectedAssetIds={selectedAssetIds}
          onClose={() => setToolPickerOpen(false)}
          onConfirm={(selection) => { setSelectedTool(selection); setToolPickerOpen(false); }}
          onClear={() => { setSelectedTool(null); setToolPickerOpen(false); }}
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
      {activeOutput && <OutputCanvas output={activeOutput} selectedModel={selectedModel} onClose={() => setActiveOutput(null)} />}
    </main>
  );
}
