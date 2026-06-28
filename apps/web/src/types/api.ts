export type ChatModel = {
  provider: string;
  model: string;
  label: string;
  enabled: boolean;
  default?: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  chat_provider?: string | null;
  chat_model?: string | null;
  updated_at?: string;
  messages?: ChatMessage[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  status?: "complete" | "streaming" | "error";
  stream_status?: string | null;
};

export type Asset = {
  id: string;
  category: "text" | "image" | "audio" | "video" | string;
  original_filename?: string;
  filename?: string;
  status: string;
  chunk_count?: number;
  scan_error?: string;
};

export type AuthState =
  | { state: "guest"; checking?: boolean }
  | { state: "unsubscribed"; userLabel: string }
  | { state: "ready"; userLabel: string; isAdmin: boolean };

export type StreamEvent =
  | { type: "conversation"; conversation: Conversation; user_message: ChatMessage; assistant_message: ChatMessage }
  | { type: "trace"; stage?: string; status?: string; total?: number; index?: number }
  | { type: "token"; delta?: string }
  | { type: "final"; answer?: string; sources?: string[] }
  | { type: "error"; error?: string }
  | { type: "done" };
