import { apiJson } from "@/lib/api";
import type { Asset, ChatModel, ChatTool, Conversation, ChatMessage, GeneratedOutput, ExamGrade } from "@/types/api";

export async function getCurrentUser() {
  return apiJson<{
    logged_in: boolean;
    has_subscription?: boolean;
    name?: string;
    phone?: string;
    is_admin?: boolean;
  }>("/api/auth/me");
}

export async function listChatModels() {
  return apiJson<{ models: ChatModel[] }>("/api/chat/models");
}

export async function listTools() {
  return apiJson<{ tools: ChatTool[] }>("/api/tools");
}

export async function getGeneratedOutput(id: string) {
  return apiJson<{ output: GeneratedOutput }>(`/api/outputs/${encodeURIComponent(id)}`);
}

export async function gradeGeneratedOutput(
  id: string,
  answers: Record<string, string | number>,
  model?: { provider: string; model: string },
) {
  return apiJson<{ grade: ExamGrade }>(`/api/outputs/${encodeURIComponent(id)}/grade`, {
    method: "POST",
    body: JSON.stringify({ answers, chat_provider: model?.provider, chat_model: model?.model }),
  });
}

export async function listConversations() {
  return apiJson<{ conversations: Conversation[] }>("/api/conversations");
}

export async function getConversationMessages(id: string) {
  return apiJson<{ conversation: Conversation; messages: ChatMessage[] }>(`/api/conversations/${encodeURIComponent(id)}/messages`);
}

export async function createConversationApi(chatProvider: string, chatModel: string) {
  return apiJson<{ conversation: Conversation }>("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ chat_provider: chatProvider, chat_model: chatModel }),
  });
}

export async function updateConversationModelApi(id: string, chatProvider: string, chatModel: string) {
  return apiJson<{ conversation: Conversation }>(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ chat_provider: chatProvider, chat_model: chatModel }),
  });
}

export async function renameConversationApi(id: string, title: string) {
  return apiJson<{ conversation: Conversation }>(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversationApi(id: string) {
  return apiJson<{ status: string }>(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function listAssets() {
  return apiJson<{ assets: Asset[] }>("/api/gallery/assets");
}

export async function uploadAsset(file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiJson<{ created?: Asset[]; rejected?: { error: string }[] }>("/api/gallery/upload", {
    method: "POST",
    body: form,
    headers: {},
  });
}
