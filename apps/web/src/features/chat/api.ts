import { apiJson } from "@/lib/api";
import type { Asset, ChatTool, Conversation, ChatMessage, GeneratedOutput, ExamGrade } from "@/types/api";

export async function getCurrentUser() {
  return apiJson<{
    logged_in: boolean;
    has_subscription?: boolean;
    name?: string;
    phone?: string;
    is_admin?: boolean;
  }>("/api/auth/me");
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
) {
  return apiJson<{ grade: ExamGrade }>(`/api/outputs/${encodeURIComponent(id)}/grade`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export async function listConversations() {
  return apiJson<{ conversations: Conversation[] }>("/api/conversations");
}

export async function getConversationMessages(id: string) {
  return apiJson<{ conversation: Conversation; messages: ChatMessage[] }>(`/api/conversations/${encodeURIComponent(id)}/messages`);
}

export async function createConversationApi() {
  return apiJson<{ conversation: Conversation }>("/api/conversations", {
    method: "POST",
    body: JSON.stringify({}),
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
