import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode, RefObject } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Brain,
  Check,
  Clock,
  Cpu,
  Database,
  ListTodo,
  Lock,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  StopCircle,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  cancelTask,
  createSession,
  createTask,
  fetchMessages,
  fetchReflections,
  fetchSessions,
  fetchStatus,
  fetchTaskEvents,
  fetchTasks,
  streamAgentChat
} from "./lib/api";
import { cn, compactNumber, formatRelativeTime } from "./lib/utils";
import type {
  ChatMessage,
  ChatSession,
  Reflection,
  StatusPayload,
  TaskEvent,
  TaskRun,
  ToolStep
} from "./types";

type View = "chat" | "tasks" | "memory" | "system";

const navItems: Array<{ id: View; label: string; icon: LucideIcon }> = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "tasks", label: "Tasks", icon: ListTodo },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "system", label: "System", icon: Settings }
];

const starterPrompts = [
  "What should I focus on next?",
  "What do you remember about my current priorities?",
  "List the files in one of my project directories.",
  "Give me the direct version:"
];

function App() {
  const [view, setView] = useState<View>("chat");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [reflections, setReflections] = useState<Reflection[]>([]);
  const [tasks, setTasks] = useState<TaskRun[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [taskEvents, setTaskEvents] = useState<TaskEvent[]>([]);
  const [input, setInput] = useState("");
  const [taskPrompt, setTaskPrompt] = useState("");
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? null,
    [selectedSessionId, sessions]
  );
  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? null,
    [selectedTaskId, tasks]
  );

  const refreshMeta = useCallback(async () => {
    const [nextSessions, nextStatus, nextReflections] = await Promise.all([
      fetchSessions(),
      fetchStatus(),
      fetchReflections()
    ]);
    setSessions(nextSessions);
    setStatus(nextStatus);
    setReflections(nextReflections);
    setSelectedSessionId((current) => current ?? nextSessions[0]?.id ?? null);
  }, []);

  const refreshTasks = useCallback(async () => {
    const nextTasks = await fetchTasks();
    setTasks(nextTasks);
    setSelectedTaskId((current) => current ?? nextTasks[0]?.id ?? null);
  }, []);

  useEffect(() => {
    refreshMeta().catch((err: Error) => setError(err.message));
    refreshTasks().catch((err: Error) => setError(err.message));
  }, [refreshMeta, refreshTasks]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshTasks().catch((err: Error) => setError(err.message));
    }, 3500);
    return () => window.clearInterval(timer);
  }, [refreshTasks]);

  useEffect(() => {
    if (selectedSessionId === null) {
      setMessages([]);
      return;
    }

    let cancelled = false;
    setIsLoadingSession(true);
    fetchMessages(selectedSessionId)
      .then((nextMessages) => {
        if (!cancelled) {
          setMessages(nextMessages.filter((message) => message.role !== "system"));
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingSession(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedSessionId]);

  useEffect(() => {
    if (selectedTaskId === null) {
      setTaskEvents([]);
      return;
    }
    let cancelled = false;
    const load = () => {
      fetchTaskEvents(selectedTaskId)
        .then((events) => {
          if (!cancelled) setTaskEvents(events);
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
    };
    load();
    const timer = window.setInterval(load, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedTaskId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [input]);

  async function startNewChat() {
    const session = await createSession();
    setSessions((current) => [session, ...current]);
    setSelectedSessionId(session.id);
    setMessages([]);
    setInput("");
    setError(null);
    setView("chat");
    textareaRef.current?.focus();
  }

  async function ensureSession() {
    if (selectedSessionId !== null) return selectedSessionId;
    const session = await createSession();
    setSessions((current) => [session, ...current]);
    setSelectedSessionId(session.id);
    return session.id;
  }

  function patchAssistant(id: string, patch: (message: ChatMessage) => ChatMessage) {
    setMessages((current) =>
      current.map((message) => (message.id === id ? patch(message) : message))
    );
  }

  async function handleSubmit(event?: FormEvent) {
    event?.preventDefault();
    const text = input.trim();
    if (!text || isSending) return;

    setError(null);
    setInput("");
    setIsSending(true);
    setView("chat");

    const localUserId = `user-${Date.now()}`;
    const localAssistantId = `assistant-${Date.now()}`;

    try {
      const sessionId = await ensureSession();
      setMessages((current) => [
        ...current,
        { id: localUserId, role: "user", content: text, timestamp: Date.now() / 1000 },
        {
          id: localAssistantId,
          role: "assistant",
          content: "",
          timestamp: Date.now() / 1000,
          pending: true,
          steps: []
        }
      ]);

      await streamAgentChat({
        sessionId,
        message: text,
        onEvent: (chatEvent) => {
          if (chatEvent.type === "tool_call") {
            const step: ToolStep = {
              name: String(chatEvent.payload?.name ?? "tool"),
              arguments: chatEvent.payload?.arguments
            };
            patchAssistant(localAssistantId, (message) => ({
              ...message,
              steps: [...(message.steps ?? []), step]
            }));
          } else if (chatEvent.type === "tool_result") {
            patchAssistant(localAssistantId, (message) => {
              const steps = [...(message.steps ?? [])];
              for (let i = steps.length - 1; i >= 0; i -= 1) {
                if (steps[i].name === chatEvent.payload?.name && steps[i].output === undefined) {
                  steps[i] = { ...steps[i], output: String(chatEvent.payload?.output ?? "") };
                  break;
                }
              }
              return { ...message, steps };
            });
          } else if (chatEvent.type === "final") {
            patchAssistant(localAssistantId, (message) => ({
              ...message,
              content: String(chatEvent.payload?.content ?? ""),
              pending: false
            }));
          } else if (chatEvent.type === "error") {
            setError(chatEvent.message);
            patchAssistant(localAssistantId, (message) => ({
              ...message,
              content: `Error: ${chatEvent.message}`,
              pending: false,
              error: true
            }));
          }
        }
      });

      // Clear any lingering pending flag if no final event arrived.
      patchAssistant(localAssistantId, (message) =>
        message.pending ? { ...message, pending: false } : message
      );
      await refreshMeta();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Chat request failed";
      setError(message);
      patchAssistant(localAssistantId, (item) => ({
        ...item,
        content: `Error: ${message}`,
        pending: false,
        error: true
      }));
    } finally {
      setIsSending(false);
      textareaRef.current?.focus();
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  async function handleCreateTask(event: FormEvent) {
    event.preventDefault();
    const prompt = taskPrompt.trim();
    if (!prompt || isCreatingTask) return;
    setIsCreatingTask(true);
    setError(null);
    try {
      const task = await createTask(prompt);
      setTaskPrompt("");
      setSelectedTaskId(task.id);
      setView("tasks");
      await refreshTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create task");
    } finally {
      setIsCreatingTask(false);
    }
  }

  async function handleCancelTask(taskId: number) {
    try {
      const task = await cancelTask(taskId);
      setTasks((current) => current.map((item) => (item.id === task.id ? task : item)));
      await refreshTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel task");
    }
  }

  const onRefresh = () => {
    refreshMeta().catch((err: Error) => setError(err.message));
    refreshTasks().catch((err: Error) => setError(err.message));
  };

  const shellProps: ShellProps = {
    tasks,
    selectedTask,
    taskEvents,
    status,
    reflections,
    error,
    taskPrompt,
    isCreatingTask,
    onTaskPromptChange: setTaskPrompt,
    onCreateTask: handleCreateTask,
    onCancelTask: handleCancelTask,
    onSelectTask: setSelectedTaskId,
    onSetView: setView,
    onRefresh
  };

  return (
    <div className="h-svh overflow-hidden bg-graphite-950 text-zinc-100">
      <div className="flex h-full flex-col lg:grid lg:grid-cols-[276px_minmax(0,1fr)]">
        <PrimaryNav
          view={view}
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          status={status}
          onView={setView}
          onNewChat={startNewChat}
          onSelectSession={(id) => {
            setSelectedSessionId(id);
            setView("chat");
          }}
        />

        <main className="min-h-0 overflow-hidden bg-graphite-925">
          {view === "chat" ? (
            <ChatView
              session={selectedSession}
              status={status}
              error={error}
              input={input}
              messages={messages}
              isLoadingSession={isLoadingSession}
              isSending={isSending}
              textareaRef={textareaRef}
              messagesEndRef={messagesEndRef}
              onInput={setInput}
              onPickPrompt={setInput}
              onKeyDown={handleComposerKeyDown}
              onSubmit={handleSubmit}
              onRefresh={onRefresh}
            />
          ) : null}
          {view === "tasks" ? <TasksView {...shellProps} /> : null}
          {view === "memory" ? <MemoryView {...shellProps} /> : null}
          {view === "system" ? <SystemView {...shellProps} /> : null}
        </main>
      </div>
    </div>
  );
}

function PrimaryNav(props: {
  view: View;
  sessions: ChatSession[];
  selectedSessionId: number | null;
  status: StatusPayload | null;
  onView: (view: View) => void;
  onNewChat: () => void;
  onSelectSession: (id: number) => void;
}) {
  return (
    <aside className="flex h-52 shrink-0 flex-col border-b border-white/10 bg-graphite-950 lg:h-svh lg:border-b-0 lg:border-r">
      <div className="flex items-center justify-between px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-white">Personal Secretary</div>
          <div className="mt-0.5 text-xs text-zinc-500">{props.status?.model ?? "local agent"}</div>
        </div>
        <button
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] text-zinc-200 transition hover:border-accent-500/70 hover:text-white"
          onClick={props.onNewChat}
          title="New chat"
        >
          <Plus size={17} />
        </button>
      </div>

      <nav className="flex gap-1 overflow-x-auto px-2 pb-2 lg:block lg:space-y-1 lg:overflow-x-visible">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => props.onView(item.id)}
              className={cn(
                "flex min-w-fit items-center gap-2 rounded-md px-3 py-2 text-sm transition lg:w-full",
                props.view === item.id
                  ? "bg-white/[0.07] text-white"
                  : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
              )}
            >
              <Icon size={16} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="hidden min-h-0 flex-1 overflow-y-auto border-t border-white/10 px-2 py-3 lg:block">
        <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-600">
          Recent Chats
        </div>
        <div className="space-y-1">
          {props.sessions.slice(0, 8).map((session) => (
            <button
              key={session.id}
              onClick={() => props.onSelectSession(session.id)}
              className={cn(
                "w-full rounded-md px-3 py-2 text-left transition",
                props.selectedSessionId === session.id && props.view === "chat"
                  ? "bg-white/[0.07] text-white"
                  : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
              )}
            >
              <div className="truncate text-sm font-medium">{session.title}</div>
              <div className="mt-1 flex justify-between gap-2 text-xs text-zinc-500">
                <span>{session.message_count} msgs</span>
                <span>{formatRelativeTime(session.updated_at)}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}

type ShellProps = {
  tasks: TaskRun[];
  selectedTask: TaskRun | null;
  taskEvents: TaskEvent[];
  status: StatusPayload | null;
  reflections: Reflection[];
  error: string | null;
  taskPrompt: string;
  isCreatingTask: boolean;
  onTaskPromptChange: (value: string) => void;
  onCreateTask: (event: FormEvent) => void;
  onCancelTask: (taskId: number) => void;
  onSelectTask: (taskId: number) => void;
  onSetView: (view: View) => void;
  onRefresh: () => void;
};

function ChatView(props: {
  session: ChatSession | null;
  status: StatusPayload | null;
  error: string | null;
  input: string;
  messages: ChatMessage[];
  isLoadingSession: boolean;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  messagesEndRef: RefObject<HTMLDivElement | null>;
  onInput: (value: string) => void;
  onPickPrompt: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: (event?: FormEvent) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-white/10 px-4 md:px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <MessageSquare size={17} className="text-accent-400" />
            <span className="truncate">{props.session?.title ?? "New chat"}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
            <span>{props.status?.model ?? "Model loading"}</span>
            {props.status?.tools?.length ? <span>· {props.status.tools.length} tools</span> : null}
            {props.error ? <span className="text-red-300">{props.error}</span> : null}
          </div>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-md border border-white/10 px-3 py-2 text-xs font-medium text-zinc-300 transition hover:border-accent-500/70 hover:text-white"
          onClick={props.onRefresh}
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </header>

      <section className="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-8">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
          {props.isLoadingSession ? (
            <LoadingState />
          ) : props.messages.length === 0 ? (
            <EmptyState onPickPrompt={props.onPickPrompt} />
          ) : (
            <AnimatePresence initial={false}>
              {props.messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
            </AnimatePresence>
          )}
          <div ref={props.messagesEndRef} />
        </div>
      </section>

      <Composer
        input={props.input}
        isSending={props.isSending}
        textareaRef={props.textareaRef}
        onChange={props.onInput}
        onKeyDown={props.onKeyDown}
        onSubmit={props.onSubmit}
      />
    </div>
  );
}

function TasksView(props: ShellProps) {
  return (
    <Page title="Tasks" kicker="Background worker queue" onRefresh={props.onRefresh} error={props.error}>
      <div className="grid min-h-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Section title="New Task">
            <TaskCreateForm
              prompt={props.taskPrompt}
              isCreating={props.isCreatingTask}
              onChange={props.onTaskPromptChange}
              onSubmit={props.onCreateTask}
            />
          </Section>
          <Section title="Queue">
            <TaskList
              tasks={props.tasks}
              selectedTaskId={props.selectedTask?.id ?? null}
              onSelect={props.onSelectTask}
            />
          </Section>
        </div>
        <Section
          title={props.selectedTask ? `Task #${props.selectedTask.id}` : "Task Detail"}
          action={
            props.selectedTask && isTaskActive(props.selectedTask) ? (
              <button
                className="inline-flex items-center gap-2 rounded-md border border-red-400/30 px-3 py-2 text-xs font-medium text-red-200 transition hover:border-red-300"
                onClick={() => props.onCancelTask(props.selectedTask!.id)}
              >
                <StopCircle size={14} />
                Cancel
              </button>
            ) : null
          }
        >
          <TaskDetail task={props.selectedTask} events={props.taskEvents} />
        </Section>
      </div>
    </Page>
  );
}

function MemoryView(props: ShellProps) {
  return (
    <Page title="Memory" kicker="Active reflections" onRefresh={props.onRefresh} error={props.error}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Section title="Active Facts">
          {props.reflections.length === 0 ? (
            <EmptyPanel text="No active reflections yet." />
          ) : (
            <div className="space-y-2">
              {props.reflections.map((reflection) => (
                <div key={reflection.id} className="rounded-md border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-zinc-300">
                  {reflection.content}
                </div>
              ))}
            </div>
          )}
        </Section>
        <Section title="Memory Stats">
          <div className="space-y-3">
            <StatBlock icon={Database} label="Messages" value={compactNumber(props.status?.messages ?? 0)} />
            <StatBlock icon={MessageSquare} label="Sessions" value={compactNumber(props.status?.sessions ?? 0)} />
            <StatBlock icon={Brain} label="Facts" value={compactNumber(props.status?.active_reflections ?? 0)} />
          </div>
        </Section>
      </div>
    </Page>
  );
}

function SystemView(props: ShellProps) {
  return (
    <Page title="System" kicker="Runtime and safety policy" onRefresh={props.onRefresh} error={props.error}>
      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Runtime">
          <div className="space-y-3">
            <Metric icon={Cpu} label="Model" value={props.status?.model ?? "Loading"} />
            <Metric icon={Server} label="Ollama" value={props.status?.ollama_host ?? "Unknown"} />
            <Metric icon={ListTodo} label="Tools" value={props.status?.tools?.join(", ") || "none"} />
          </div>
        </Section>
        <Section title="Safety Defaults">
          <div className="space-y-2 text-sm text-zinc-300">
            <PolicyLine text="Tools exposed to the model are read-only." />
            <PolicyLine text="The approval gate re-enters when the first write tool is added." />
            <PolicyLine text="Background tasks run read-only and do not take external actions." />
          </div>
        </Section>
        <Section title="Capabilities">
          <div className="space-y-2">
            {Object.entries(props.status?.capabilities ?? {}).map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-3 text-sm">
                <span className="capitalize text-zinc-400">{key.replace(/_/g, " ")}</span>
                <span className={cn("text-right", value === true ? "text-emerald-300" : "text-zinc-500")}>
                  {value === true ? "online" : String(value)}
                </span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </Page>
  );
}

function Page(props: {
  title: string;
  kicker: string;
  children: ReactNode;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="h-full min-h-0 overflow-y-auto px-4 py-5 md:px-7"
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <header className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-accent-400">
              {props.kicker}
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white md:text-3xl">
              {props.title}
            </h1>
            {props.error ? <div className="mt-2 text-sm text-red-300">{props.error}</div> : null}
          </div>
          <button
            className="inline-flex items-center gap-2 rounded-md border border-white/10 px-3 py-2 text-xs font-medium text-zinc-300 transition hover:border-accent-500/70 hover:text-white"
            onClick={props.onRefresh}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </header>
        {props.children}
      </div>
    </motion.div>
  );
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.025] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function StatBlock({ icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  const Icon = icon;
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
      <div className="flex items-center gap-3">
        <div className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-accent-500/10 text-accent-400">
          <Icon size={17} />
        </div>
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">{label}</div>
          <div className="truncate text-lg font-semibold text-white">{value}</div>
        </div>
      </div>
    </div>
  );
}

function TaskCreateForm(props: {
  prompt: string;
  isCreating: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form onSubmit={props.onSubmit} className="space-y-3">
      <textarea
        value={props.prompt}
        onChange={(event) => props.onChange(event.target.value)}
        rows={5}
        placeholder="Delegate a local read-only task..."
        className="w-full resize-none rounded-md border border-white/10 bg-graphite-900 px-3 py-3 text-sm leading-6 text-white outline-none transition focus:border-accent-500/70"
      />
      <button
        disabled={props.isCreating || !props.prompt.trim()}
        className="inline-flex items-center gap-2 rounded-md bg-accent-500 px-3 py-2 text-sm font-medium text-white transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-zinc-500"
      >
        <Plus size={15} />
        Queue Task
      </button>
    </form>
  );
}

function TaskList(props: {
  tasks: TaskRun[];
  selectedTaskId: number | null;
  onSelect: (taskId: number) => void;
}) {
  if (props.tasks.length === 0) return <EmptyPanel text="No tasks yet." />;
  return (
    <div className="space-y-2">
      {props.tasks.map((task) => (
        <button
          key={task.id}
          onClick={() => props.onSelect(task.id)}
          className={cn(
            "w-full rounded-md border p-3 text-left transition",
            props.selectedTaskId === task.id
              ? "border-accent-500/50 bg-accent-500/10"
              : "border-white/10 bg-white/[0.03] hover:border-white/20"
          )}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 truncate text-sm font-medium text-white">{task.title}</div>
            <StatusPill status={task.cancel_requested && isTaskActive(task) ? "cancelling" : task.status} />
          </div>
          <div className="mt-1 line-clamp-2 text-xs leading-5 text-zinc-500">{task.prompt}</div>
          <div className="mt-2 text-xs text-zinc-600">{formatRelativeTime(task.updated_at)}</div>
        </button>
      ))}
    </div>
  );
}

function TaskDetail({ task, events }: { task: TaskRun | null; events: TaskEvent[] }) {
  if (!task) return <EmptyPanel text="Select a task to inspect its run log." />;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-white/10 bg-graphite-900 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-white">{task.title}</div>
            <div className="mt-1 text-xs text-zinc-500">Worker: {task.worker_id ?? "not claimed"}</div>
          </div>
          <StatusPill status={task.cancel_requested && isTaskActive(task) ? "cancelling" : task.status} />
        </div>
        <p className="mt-4 text-sm leading-6 text-zinc-300">{task.prompt}</p>
        {task.final_result ? (
          <div className="mt-4 rounded-md border border-emerald-400/20 bg-emerald-950/20 p-3 text-sm leading-6 text-emerald-100">
            <Markdown content={task.final_result} />
          </div>
        ) : null}
        {task.error ? (
          <div className="mt-4 rounded-md border border-red-400/20 bg-red-950/20 p-3 text-sm leading-6 text-red-100">
            {task.error}
          </div>
        ) : null}
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Event Log</div>
        {events.length === 0 ? <EmptyPanel text="No events yet." /> : events.map((event) => <TaskEventRow key={event.id} event={event} />)}
      </div>
    </div>
  );
}

function TaskEventRow({ event }: { event: TaskEvent }) {
  const payload = parsePayload(event.payload);
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.025] p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-zinc-200">{event.message}</div>
          <div className="mt-1 text-xs text-zinc-600">
            {event.event_type} · {formatRelativeTime(event.timestamp)}
          </div>
        </div>
        <EventIcon type={event.event_type} />
      </div>
      {payload ? (
        <pre className="mt-3 max-h-52 overflow-auto rounded-md bg-black/25 p-3 text-xs leading-5 text-zinc-400">
          {JSON.stringify(payload, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function EventIcon({ type }: { type: string }) {
  if (type.includes("tool")) return <Search size={15} className="text-accent-400" />;
  if (type.includes("failed")) return <X size={15} className="text-red-300" />;
  if (type.includes("completed") || type.includes("final")) return <Check size={15} className="text-emerald-300" />;
  return <Clock size={15} className="text-zinc-500" />;
}

function Metric(props: { icon: LucideIcon; label: string; value: string }) {
  const Icon = props.icon;
  return (
    <div className="flex items-center gap-3 rounded-md border border-white/10 bg-white/[0.03] p-3">
      <div className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/[0.05] text-accent-400">
        <Icon size={15} />
      </div>
      <div className="min-w-0">
        <div className="text-xs text-zinc-500">{props.label}</div>
        <div className="truncate text-sm font-medium text-zinc-200">{props.value}</div>
      </div>
    </div>
  );
}

function PolicyLine({ text }: { text: string }) {
  return (
    <div className="flex gap-2">
      <Lock size={15} className="mt-0.5 shrink-0 text-accent-400" />
      <span>{text}</span>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "online" || status === "completed" || status === "approved"
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
      : status === "running" || status === "queued" || status === "pending" || status === "cancelling"
        ? "border-accent-400/30 bg-accent-500/10 text-accent-200"
        : status === "failed" || status === "offline" || status === "rejected"
          ? "border-red-400/30 bg-red-500/10 text-red-200"
          : "border-white/10 bg-white/[0.04] text-zinc-400";
  return (
    <span className={cn("inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium", tone)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-white/10 px-3 py-5 text-sm text-zinc-500">
      {text}
    </div>
  );
}

function EmptyState({ onPickPrompt }: { onPickPrompt: (value: string) => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex min-h-[52vh] flex-col justify-center">
      <div className="max-w-2xl">
        <div className="inline-flex items-center gap-2 rounded-full border border-accent-500/30 bg-accent-500/10 px-3 py-1 text-xs font-medium text-accent-400">
          <Bot size={14} />
          Memory-backed local assistant
        </div>
        <h1 className="mt-5 text-3xl font-semibold tracking-tight text-white md:text-5xl">
          What needs your attention?
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-zinc-400 md:text-base">
          Start with a task, decision, draft, or question. The secretary pulls relevant memory and can use its tools before answering.
        </p>
        <div className="mt-7 grid gap-2 sm:grid-cols-2">
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              onClick={() => onPickPrompt(prompt)}
              className="rounded-md border border-white/10 bg-white/[0.03] px-4 py-3 text-left text-sm text-zinc-300 transition hover:border-accent-500/60 hover:bg-accent-500/10 hover:text-white"
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

function LoadingState() {
  return <div className="flex min-h-[45vh] items-center justify-center text-sm text-zinc-500">Loading conversation...</div>;
}

function ToolSteps({ steps }: { steps: ToolStep[] }) {
  if (!steps.length) return null;
  return (
    <div className="mb-2 space-y-1">
      {steps.map((step, index) => (
        <div
          key={`${step.name}-${index}`}
          className="flex items-center gap-2 rounded-md border border-white/10 bg-black/20 px-2 py-1 text-xs text-zinc-400"
        >
          <Search size={13} className="text-accent-400" />
          <span className="font-medium text-zinc-300">{step.name}</span>
          <span className="text-zinc-600">
            {step.output === undefined ? "running…" : `→ ${truncate(step.output, 64)}`}
          </span>
        </div>
      ))}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.16 }}
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "max-w-[86%] rounded-lg px-4 py-3 text-sm leading-6 md:max-w-[78%]",
          isUser ? "bg-accent-500 text-white" : "border border-white/10 bg-white/[0.035] text-zinc-200",
          message.error && "border-red-400/40 bg-red-950/20 text-red-100"
        )}
      >
        <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] opacity-70">
          {isUser ? "You" : "Secretary"}
          {message.pending ? <span className="typing-dot" /> : null}
        </div>
        {!isUser && message.steps?.length ? <ToolSteps steps={message.steps} /> : null}
        {message.content ? (
          <Markdown content={message.content} />
        ) : message.pending ? (
          <div className="text-zinc-400">Thinking...</div>
        ) : null}
      </div>
    </motion.article>
  );
}

function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
        a: ({ children, href }) => (
          <a className="text-accent-400 underline underline-offset-4" href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        code: ({ children, className }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) return <code className={className}>{children}</code>;
          return <code className="rounded bg-black/30 px-1.5 py-0.5 text-[0.9em] text-zinc-100">{children}</code>;
        },
        pre: ({ children }) => (
          <pre className="mb-3 overflow-x-auto rounded-md border border-white/10 bg-black/35 p-3 text-xs leading-5 text-zinc-100 last:mb-0">
            {children}
          </pre>
        )
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function Composer(props: {
  input: string;
  isSending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: (event?: FormEvent) => void;
}) {
  return (
    <form onSubmit={props.onSubmit} className="border-t border-white/10 bg-graphite-925 px-4 py-4 shadow-composer md:px-8">
      <div className="mx-auto flex max-w-4xl items-end gap-3 rounded-lg border border-white/10 bg-graphite-900 p-2 transition-within focus-within:border-accent-500/70">
        <textarea
          ref={props.textareaRef}
          value={props.input}
          onChange={(event) => props.onChange(event.target.value)}
          onKeyDown={props.onKeyDown}
          rows={1}
          placeholder="Message your secretary..."
          className="max-h-44 min-h-11 flex-1 resize-none bg-transparent px-3 py-3 text-sm leading-6 text-white outline-none placeholder:text-zinc-600"
        />
        <button
          type="submit"
          disabled={props.isSending || !props.input.trim()}
          className="mb-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-accent-500 text-white transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-zinc-500"
          title="Send"
        >
          <Send size={17} />
        </button>
      </div>
    </form>
  );
}

function isTaskActive(task: TaskRun) {
  return !["completed", "failed", "cancelled"].includes(task.status);
}

function truncate(value: string, max: number) {
  const oneLine = value.replace(/\s+/g, " ").trim();
  return oneLine.length > max ? `${oneLine.slice(0, max)}…` : oneLine;
}

function parsePayload(payload: string | null) {
  if (!payload) return null;
  try {
    return JSON.parse(payload) as unknown;
  } catch {
    return payload;
  }
}

export default App;
