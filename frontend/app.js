import { TEXT } from "./i18n.js";
import { createUI } from "./ui.js";
import { startChatStream, isAbortError } from "./sse.js";
import { createStreamParser } from "./parser.js";

// 同源部署时保持为空字符串；跨域静态托管时可改为 "http://127.0.0.1:8000"。
const BASE_URL = "";

const state = {
  status: "idle", // idle | streaming | error | stopped
  mode: TEXT.status.unknownMode,
  topK: 3,
  useTools: true,

  sessionId: "demo-001",
  sessions: new Map(),
  lastUserMessageBySession: new Map(),

  ingest: {
    kind: "idle",
    text: TEXT.settings.ingestIdle,
  },

  debug: createEmptyDebug(),
  activeStream: null,
  activeParser: null,
  currentAssistantMessage: null,
  stopRequested: false,
};

const ui = createUI(TEXT);

boot();

function boot() {
  ui.applyStaticText();
  ui.bindEvents({
    onSend: () => sendChat(),
    onStop: () => stopChat(),
    onRetry: () => retryChat(),
    onIngest: () => ingestKnowledge(),
    onSwitchSession: (value) => switchSession(value, true),
    onSessionSelect: (value) => switchSession(value, false),
    onClearSession: () => clearCurrentSession(),
    onSettingsChange: ({ topK, useTools }) => updateSettings(topK, useTools),
    onQuickChip: (value) => sendChat(value),
    onDebugToggle: () => undefined,
    onTabChange: () => undefined,
    onCopyDebug: (rawText) => copyDebug(rawText),
  });

  ensureSession(state.sessionId);
  ui.setSessionInput(state.sessionId);
  ui.setSettings({ topK: state.topK, useTools: state.useTools });
  ui.renderSessionOptions(Array.from(state.sessions.keys()), state.sessionId);
  ui.renderMessages(ensureSession(state.sessionId));
  ui.renderIngestBanner(state.ingest);
  ui.renderDebug(getDebugViewData());
  ui.setStreaming(false);
  ui.setDebugOpen(false);
  ui.setActiveTab("trace");
  renderStatus();
  fetchHealthMode();
}

function ensureSession(sessionId) {
  if (!state.sessions.has(sessionId)) {
    state.sessions.set(sessionId, []);
  }
  return state.sessions.get(sessionId);
}

function switchSession(nextSessionId, showToast) {
  const sid = String(nextSessionId || "").trim();
  if (!sid) return;

  state.sessionId = sid;
  ensureSession(sid);

  ui.setSessionInput(sid);
  ui.renderSessionOptions(Array.from(state.sessions.keys()), sid);
  ui.renderMessages(ensureSession(sid));

  if (showToast) {
    ui.showToast("info", TEXT.toast.sessionSwitched);
  }
}

function clearCurrentSession() {
  state.sessions.set(state.sessionId, []);
  state.lastUserMessageBySession.delete(state.sessionId);
  ui.renderMessages(ensureSession(state.sessionId));
  ui.showToast("info", TEXT.toast.sessionCleared);
}

function updateSettings(topK, useTools) {
  state.topK = Number.isFinite(topK) ? Math.max(1, Math.min(10, topK)) : 3;
  state.useTools = Boolean(useTools);
  renderStatus();
}

function appendMessage(role, content) {
  const history = ensureSession(state.sessionId);
  const item = {
    role,
    content: sanitizePath(String(content || "")),
    ts: Date.now(),
  };
  history.push(item);
  ui.renderMessages(history);
  return item;
}

/**
 * 流式场景下始终复用同一个 assistant 消息对象，
 * 可以避免列表不断新增节点造成抖动。
 */
function appendAssistantChunk(chunk) {
  const text = sanitizePath(String(chunk || ""));
  if (!text) return;

  if (!state.currentAssistantMessage) {
    state.currentAssistantMessage = appendMessage("assistant", "");
  }

  state.currentAssistantMessage.content += text;
  ui.renderMessages(ensureSession(state.sessionId));
}

function resetDebug() {
  state.debug = createEmptyDebug();
  ui.renderDebug(getDebugViewData());
}

function renderStatus() {
  const label = TEXT.status[state.status] || TEXT.status.idle;
  const mode = state.mode || TEXT.status.unknownMode;
  const tools = state.useTools ? TEXT.status.toolsOn : TEXT.status.toolsOff;

  ui.renderStatus({
    code: state.status,
    label,
    mode,
    topK: state.topK,
    tools,
  });
}

function finishStream(nextStatus) {
  if (state.currentAssistantMessage && !state.currentAssistantMessage.content.trim()) {
    state.currentAssistantMessage.content = TEXT.system.emptyAssistant;
  }

  state.activeParser?.flush();
  state.activeParser = null;
  state.activeStream = null;
  state.currentAssistantMessage = null;
  state.stopRequested = false;
  state.status = nextStatus;

  ui.setStreaming(false);
  ui.renderMessages(ensureSession(state.sessionId));
  renderStatus();
}

async function sendChat(overrideMessage = "") {
  if (state.activeStream) {
    ui.showToast("info", TEXT.toast.busyStreaming);
    return;
  }

  const message = String(overrideMessage || ui.getMessage()).trim();
  if (!message) {
    ui.showToast("info", TEXT.toast.emptyMessage);
    return;
  }

  state.lastUserMessageBySession.set(state.sessionId, message);
  appendMessage("user", message);
  state.currentAssistantMessage = appendMessage("assistant", "");
  ui.clearMessage();

  resetDebug();
  state.status = "streaming";
  renderStatus();
  ui.setStreaming(true);

  const payload = {
    session_id: state.sessionId,
    message,
    top_k: state.topK,
    use_tools: state.useTools,
    show_debug: true,
  };

  state.stopRequested = false;
  state.activeParser = createStreamParser({
    onPlan: (line) => {
      if (!state.debug.plan.includes(line)) {
        state.debug.plan.push(line);
        ui.renderDebug(getDebugViewData());
      }
    },
    onStep: (line) => {
      state.debug.steps.push(line);
      ui.renderDebug(getDebugViewData());
    },
    onReact: (item) => {
      const old = state.debug.reactMap.get(item.index) || {
        index: item.index,
        thought: "",
        action: "",
        observation: "",
      };
      old[item.field] = item.value;
      state.debug.reactMap.set(item.index, old);
      ui.renderDebug(getDebugViewData());
    },
    onAnswer: (chunk) => {
      appendAssistantChunk(chunk);
    },
    onDebug: (obj) => {
      mergeDebugObject(obj);
      ui.renderDebug(getDebugViewData());
    },
    onTool: (tool) => {
      state.debug.tools.push(sanitizeValue(tool));
      ui.renderDebug(getDebugViewData());
    },
    onRetrieval: (row) => {
      state.debug.retrieval.push(normalizeRetrieval(sanitizeValue(row), state.debug.retrieval.length));
      ui.renderDebug(getDebugViewData());
    },
    onDone: () => {
      if (state.status === "streaming") {
        finishStream("idle");
      }
    },
    onError: (messageText) => {
      state.debug.steps.push(sanitizePath(String(messageText || "")));
      ui.renderDebug(getDebugViewData());
    },
  });

  state.activeStream = startChatStream({
    baseUrl: BASE_URL,
    payload,
    onEvent: (evt) => {
      state.activeParser?.handleSseEvent(evt);
    },
  });

  try {
    await state.activeStream.done;

    if (state.status === "streaming") {
      finishStream("idle");
    }
  } catch (error) {
    if (isAbortError(error) || state.stopRequested) {
      appendMessage("system", TEXT.system.stoppedMessage);
      finishStream("stopped");
      ui.showToast("info", TEXT.toast.stopDone);
      return;
    }

    state.debug.steps.push(friendlyError(error));
    ui.renderDebug(getDebugViewData());
    finishStream("error");
    ui.showToast("error", friendlyError(error));
  }
}

function stopChat() {
  if (!state.activeStream) return;
  state.stopRequested = true;
  state.activeStream.abort();
}

function retryChat() {
  if (state.activeStream) {
    ui.showToast("info", TEXT.toast.busyStreaming);
    return;
  }

  const lastMessage = state.lastUserMessageBySession.get(state.sessionId);
  if (!lastMessage) {
    ui.showToast("info", TEXT.toast.noRetryMessage);
    return;
  }

  ui.showToast("info", TEXT.toast.retryDone);
  sendChat(lastMessage);
}

async function ingestKnowledge() {
  if (state.activeStream) {
    ui.showToast("info", TEXT.toast.busyStreaming);
    return;
  }

  ui.setIngestBusy(true);
  state.ingest = {
    kind: "idle",
    text: TEXT.settings.ingestLoading,
  };
  ui.renderIngestBanner(state.ingest);

  try {
    const response = await fetch(`${BASE_URL}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_path: "data/faq.md" }),
    });

    const payload = await response.json();
    const data = sanitizeValue(payload);

    const ok = response.ok && data.status === "ok";
    const mode = String(data.mode || state.mode || TEXT.status.unknownMode);
    const chunks = data.chunks ?? "-";
    const source = typeof data.source === "string" ? sanitizePath(data.source) : "";

    state.mode = mode;
    state.ingest = {
      kind: ok ? "success" : "error",
      text: ok
        ? TEXT.settings.ingestSuccess(mode, chunks, source)
        : TEXT.settings.ingestFail,
    };

    if (data && typeof data === "object") {
      mergeDebugObject(data);
    }

    ui.renderIngestBanner(state.ingest);
    ui.renderDebug(getDebugViewData());
    renderStatus();
    ui.showToast(ok ? "success" : "error", ok ? TEXT.toast.ingestSuccess : TEXT.toast.ingestFail);
  } catch {
    state.ingest = {
      kind: "error",
      text: TEXT.settings.ingestFail,
    };
    ui.renderIngestBanner(state.ingest);
    ui.showToast("error", TEXT.toast.ingestFail);
  } finally {
    ui.setIngestBusy(false);
  }
}

async function fetchHealthMode() {
  try {
    const response = await fetch(`${BASE_URL}/health`);
    if (!response.ok) return;
    const data = await response.json();
    if (data && data.llm_mode) {
      state.mode = sanitizePath(String(data.llm_mode));
      renderStatus();
    }
  } catch {
    // 健康检查失败不阻塞主流程
  }
}

function mergeDebugObject(raw) {
  const data = sanitizeValue(raw);
  state.debug.raw = data;
  state.debug.trace = data.trace || state.debug.trace;

  if (state.debug.trace) {
    state.debug.traceSummary = buildTraceSummary(state.debug.trace);
  }

  const plan = data.plan || data.execution?.plan || data.trace?.plan?.map((item) => item.content);
  if (Array.isArray(plan) && plan.length) {
    state.debug.plan = plan.map((item) => String(item));
  }

  const reactList = data.react_trace || data.execution?.react_trace || data.react;
  if (Array.isArray(reactList) && reactList.length) {
    state.debug.reactMap.clear();
    reactList.forEach((item, idx) => {
      state.debug.reactMap.set(idx + 1, {
        index: idx + 1,
        thought: String(item.thought || ""),
        action: String(item.action || ""),
        observation: String(item.observation || ""),
      });
    });
  }

  const tools = data.tool_outputs || data.execution?.tool_outputs || data.tools;
  const traceTools = data.trace?.tool_calls;
  const effectiveTools = Array.isArray(tools) && tools.length ? tools : traceTools;
  if (Array.isArray(effectiveTools) && effectiveTools.length) {
    state.debug.tools = effectiveTools.map((item) => sanitizeValue(item));
  }

  const contexts = data.retrieval || data.knowledge?.retrieval_docs || data.knowledge?.contexts || data.contexts;
  const traceHits = data.trace?.retrieval?.hits;
  const effectiveContexts = Array.isArray(contexts) && contexts.length ? contexts : traceHits;
  if (Array.isArray(effectiveContexts) && effectiveContexts.length) {
    state.debug.retrieval = effectiveContexts.slice(0, state.topK).map((item, idx) => normalizeRetrieval(item, idx));
  }
}

function normalizeRetrieval(item, idx) {
  if (typeof item === "string") {
    return {
      rank: idx + 1,
      snippet: clipSnippet(item),
    };
  }

  const text = item?.text || item?.content || item?.document || JSON.stringify(item);
  const snippet = item?.snippet || text;
  const source = item?.metadata?.source || item?.source || `hit-${idx + 1}`;
  return {
    rank: item?.rank || idx + 1,
    source: sanitizePath(String(source)),
    snippet: clipSnippet(String(snippet || "")),
  };
}

function getDebugViewData() {
  const react = Array.from(state.debug.reactMap.values()).sort((a, b) => a.index - b.index);
  return {
    plan: state.debug.plan,
    steps: [...state.debug.traceSummary, ...state.debug.steps],
    react,
    retrieval: state.debug.retrieval,
    tools: state.debug.tools,
    raw: state.debug.raw,
  };
}

function createEmptyDebug() {
  return {
    plan: [],
    steps: [],
    reactMap: new Map(),
    retrieval: [],
    tools: [],
    raw: {},
    trace: null,
    traceSummary: [],
  };
}

function buildTraceSummary(trace) {
  if (!trace || typeof trace !== "object") return [];

  const lines = [];
  if (trace.trace_id) {
    lines.push(`TRACE ${trace.trace_id}`);
  }

  const latency = Number.isFinite(trace.latency_ms) ? `${trace.latency_ms}ms` : "-";
  const status = trace.status || "unknown";
  lines.push(`Status: ${status} · Latency: ${latency}`);

  const llmMode = trace.llm?.mode || "-";
  const llmModel = trace.llm?.model || "-";
  lines.push(`LLM: ${llmMode} / ${llmModel}`);

  if (trace.error?.type) {
    lines.push(`Error Type: ${trace.error.type}`);
  }

  return lines;
}

function clipSnippet(text) {
  const oneLine = sanitizePath(String(text || "").replace(/\s+/g, " ").trim());
  if (oneLine.length <= 240) return oneLine;
  return `${oneLine.slice(0, 240)}...`;
}

function copyDebug(rawText) {
  navigator.clipboard.writeText(rawText || "{}").then(() => {
    ui.showToast("success", TEXT.toast.copied);
  }).catch(() => {
    ui.showToast("error", TEXT.toast.copyFail);
  });
}

function friendlyError(error) {
  const raw = String(error?.message || error || "");
  if (raw.startsWith("HTTP_")) {
    const code = raw.replace("HTTP_", "");
    return TEXT.toast.httpFail(code);
  }
  return TEXT.toast.networkError;
}

/**
 * 安全展示：把绝对路径转换为文件名，避免前端泄露本机目录结构。
 */
function sanitizePath(text) {
  if (typeof text !== "string") return text;

  const winPattern = /[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*/g;
  const unixPattern = /(^|[\s(])((?:\/[^\/\s"')]+){2,})(?=$|[\s)])/g;

  let value = text.replace(winPattern, (full) => basename(full));
  value = value.replace(unixPattern, (full, prefix, path) => {
    if (path.includes("://")) return full;
    return `${prefix}${basename(path)}`;
  });

  return value;
}

function basename(path) {
  const normalized = String(path || "").replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || normalized;
}

function sanitizeValue(value) {
  if (typeof value === "string") return sanitizePath(value);
  if (Array.isArray(value)) return value.map((item) => sanitizeValue(item));
  if (value && typeof value === "object") {
    const out = {};
    Object.keys(value).forEach((key) => {
      out[key] = sanitizeValue(value[key]);
    });
    return out;
  }
  return value;
}
