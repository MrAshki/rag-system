export type ChatModel = {
  provider: string;
  model: string;
  label: string;
  enabled: boolean;
  default?: boolean;
};

export type ToolParamOption = {
  value: string;
  label: string;
};

export type ToolParamSchema = {
  id: string;
  label: string;
  type: "select" | "number" | "text" | "textarea" | "boolean";
  required?: boolean;
  default?: string | number | boolean;
  min?: number;
  max?: number;
  placeholder?: string;
  options?: ToolParamOption[];
};

export type ChatTool = {
  id: string;
  title: string;
  category: string;
  description: string;
  requires_assets: boolean;
  output_type: string;
  params_schema: ToolParamSchema[];
};

export type SelectedTool = {
  tool: ChatTool;
  params: Record<string, string | number | boolean>;
  assetIds: string[];
};

export type GeneratedOutput = {
  id: string;
  type: string;
  title: string;
  content_json?: Record<string, unknown>;
  content_markdown: string;
  source_asset_ids?: string[];
  template_id?: string | null;
  template_params?: Record<string, string | number | boolean>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ExamGradeQuestion = {
  id: string;
  type: "multiple_choice" | "descriptive";
  score: number;
  max_score: number;
  correct?: boolean;
  selected_index?: number | null;
  answer_index?: number | null;
  feedback?: string;
  sample_answer?: string;
  rubric?: string[];
};

export type ExamGrade = {
  total_score: number;
  total_max: number;
  objective_score: number;
  objective_max: number;
  descriptive_score: number;
  descriptive_max: number;
  questions: ExamGradeQuestion[];
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
  streamStatus?: string | null;
  mode?: string | null;
  tool_id?: string | null;
  tool_title?: string | null;
  tool_params?: Record<string, string | number | boolean>;
  generated_output_id?: string | null;
  generated_output?: GeneratedOutput | null;
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
  | { type: "trace"; stage?: string; status?: string; total?: number; index?: number; tool_id?: string; unit_title?: string; source?: string; cached?: boolean }
  | { type: "token"; delta?: string }
  | { type: "final"; answer?: string; sources?: string[]; generated_output?: GeneratedOutput }
  | { type: "error"; error?: string }
  | { type: "done" };
