import type {
  ChatEvent,
  ChatMessage,
  ChatSession,
  Reflection,
  StatusPayload,
  TaskEvent,
  TaskRun
} from "../types";

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function sendJson<T>(url: string, method: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchSessions() {
  const data = await getJson<{ sessions: ChatSession[] }>("/api/sessions");
  return data.sessions;
}

export function createSession(title?: string) {
  return sendJson<ChatSession>("/api/sessions", "POST", { title });
}

export async function fetchMessages(sessionId: number) {
  const data = await getJson<{ messages: ChatMessage[] }>(
    `/api/sessions/${sessionId}/messages`
  );
  return data.messages;
}

export async function fetchStatus() {
  return getJson<StatusPayload>("/api/status");
}

export async function fetchReflections() {
  const data = await getJson<{ reflections: Reflection[] }>("/api/reflections");
  return data.reflections;
}

export async function fetchTasks() {
  const data = await getJson<{ tasks: TaskRun[] }>("/api/tasks");
  return data.tasks;
}

export function createTask(prompt: string, title?: string) {
  return sendJson<TaskRun>("/api/tasks", "POST", { prompt, title });
}

export function cancelTask(taskId: number) {
  return sendJson<TaskRun>(`/api/tasks/${taskId}`, "PATCH", { action: "cancel" });
}

export async function fetchTaskEvents(taskId: number) {
  const data = await getJson<{ events: TaskEvent[] }>(`/api/tasks/${taskId}/events`);
  return data.events;
}

/**
 * Drive the agent loop and receive its structured events (Server-Sent Events).
 * The backend runs the ReAct loop and streams: session -> model_step ->
 * tool_call -> tool_result -> final (or error). Each SSE frame is `data: {json}`.
 */
export async function streamAgentChat(params: {
  sessionId: number;
  message: string;
  onEvent: (event: ChatEvent) => void;
}) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: params.sessionId, message: params.message })
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error("Response body is not readable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const drain = () => {
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (dataLine) {
        const json = dataLine.slice(5).trim();
        if (json) {
          try {
            params.onEvent(JSON.parse(json) as ChatEvent);
          } catch {
            // ignore malformed frames
          }
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    drain();
  }
  buffer += decoder.decode();
  drain();
}
