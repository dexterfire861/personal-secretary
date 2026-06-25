export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface ChatSession {
  id: number;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  last_message: string | null;
}

export interface ToolStep {
  name: string;
  arguments?: unknown;
  output?: string;
}

export interface ChatMessage {
  id: number | string;
  role: MessageRole;
  content: string;
  timestamp?: number;
  pending?: boolean;
  error?: boolean;
  steps?: ToolStep[];
}

export interface Reflection {
  id: number;
  content: string;
}

export interface StatusPayload {
  model: string;
  ollama_host: string;
  messages: number;
  sessions: number;
  active_reflections: number;
  tools: string[];
  capabilities: Record<string, boolean | string>;
}

export interface TaskRun {
  id: number;
  title: string;
  prompt: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  final_result: string | null;
  error: string | null;
  cancel_requested: boolean;
  worker_id: string | null;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  completed_at: number | null;
}

export interface TaskEvent {
  id: number;
  task_id: number;
  event_type: string;
  message: string;
  payload: string | null;
  timestamp: number;
}

// Streamed by POST /api/chat as Server-Sent Events while the agent loop runs.
export interface ChatEvent {
  type:
    | "session"
    | "model_step"
    | "assistant_tool_plan"
    | "tool_call"
    | "tool_result"
    | "final"
    | "error";
  message: string;
  payload?: {
    session_id?: number;
    name?: string;
    arguments?: unknown;
    output?: string;
    content?: string;
    [key: string]: unknown;
  } | null;
}
