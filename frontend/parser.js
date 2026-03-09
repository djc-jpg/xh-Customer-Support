/**
 * 增量解析器（状态机）：
 * 1) 兼容标准 SSE event/data
 * 2) 兼容 legacy 文本标签流 [PLAN]/[EXECUTE]/[ReAct]/[FINAL_ANSWER]/[DONE]
 * 3) 把“原始流”转换为结构化事件，降低 app.js 复杂度
 */
export function createStreamParser(handlers = {}) {
  const state = {
    legacySection: "unknown",
    legacyBuffer: "",
    planBuffer: "",
    stepBuffer: "",
    reactBuffer: "",
    answerBuffer: "",
    answerStarted: false,
  };

  function reset() {
    state.legacySection = "unknown";
    state.legacyBuffer = "";
    state.planBuffer = "";
    state.stepBuffer = "";
    state.reactBuffer = "";
    state.answerBuffer = "";
    state.answerStarted = false;
  }

  function handleSseEvent(evt) {
    const event = (evt?.event || "message").toLowerCase();
    const data = evt?.data ?? "";

    if (String(data).trim() === "[DONE]") {
      flush();
      handlers.onDone?.();
      return;
    }

    const parsed = tryParseJson(data);
    if (parsed && typeof parsed === "object" && "type" in parsed) {
      handleTyped(String(parsed.type), parsed.content, parsed);
      return;
    }

    if (event !== "message") {
      handleTyped(event, data, { event, data });
      return;
    }

    handleLegacyChunk(String(data));
  }

  function flush() {
    flushLineBuffer("planBuffer", emitPlanLine);
    flushLineBuffer("stepBuffer", emitStepLine);
    flushLineBuffer("reactBuffer", emitReactLine);

    if (state.legacyBuffer.trim()) {
      routeLegacyLine(state.legacyBuffer);
      state.legacyBuffer = "";
    }

    if (state.answerBuffer) {
      emitAnswerChunk(state.answerBuffer);
      state.answerBuffer = "";
    }
  }

  function handleTyped(type, content, raw) {
    const normalizedType = String(type || "").toLowerCase();
    const text = typeof content === "string" ? content : String(content ?? "");

    if (normalizedType === "done") {
      flush();
      handlers.onDone?.();
      return;
    }
    if (normalizedType === "plan") {
      pushLineBuffer("planBuffer", text, emitPlanLine);
      return;
    }
    if (normalizedType === "step" || normalizedType === "execute") {
      pushLineBuffer("stepBuffer", text, emitStepLine);
      return;
    }
    if (normalizedType === "react") {
      pushLineBuffer("reactBuffer", text, emitReactLine);
      return;
    }
    if (normalizedType === "token") {
      emitAnswerChunk(text);
      return;
    }
    if (normalizedType === "answer" || normalizedType === "final_answer") {
      pushAnswerText(text);
      return;
    }
    if (normalizedType === "debug" || normalizedType === "meta") {
      emitDebug(content, raw);
      return;
    }
    if (normalizedType === "tool") {
      handlers.onTool?.(safeObject(content, { value: text }));
      return;
    }
    if (normalizedType === "retrieval") {
      handlers.onRetrieval?.(safeObject(content, { value: text }));
      return;
    }
    if (normalizedType === "error") {
      handlers.onError?.(text || "error");
      return;
    }

    if (raw && typeof raw === "object") {
      handlers.onDebug?.(raw);
      return;
    }

    if (text.trim()) {
      handlers.onStep?.(text.trim());
    }
  }

  function emitDebug(content, fallbackRaw) {
    let payload = content;
    if (typeof payload === "string") {
      payload = tryParseJson(payload) ?? { message: payload };
    }
    if (!payload || typeof payload !== "object") {
      payload = fallbackRaw ?? { message: String(content ?? "") };
    }
    handlers.onDebug?.(payload);
  }

  function handleLegacyChunk(text) {
    state.legacyBuffer += text;

    let lineEnd = state.legacyBuffer.indexOf("\n");
    while (lineEnd >= 0) {
      const line = state.legacyBuffer.slice(0, lineEnd);
      state.legacyBuffer = state.legacyBuffer.slice(lineEnd + 1);
      routeLegacyLine(line);
      lineEnd = state.legacyBuffer.indexOf("\n");
    }
  }

  function routeLegacyLine(rawLine) {
    const line = String(rawLine || "");
    const trimmed = line.trim();
    if (!trimmed) return;

    if (trimmed.includes("[DONE]")) {
      flush();
      handlers.onDone?.();
      return;
    }

    if (trimmed.includes("[PLAN]")) {
      state.legacySection = "plan";
      const rest = trimmed.replace("[PLAN]", "").trim();
      if (rest) emitPlanLine(rest);
      return;
    }

    if (trimmed.includes("[FINAL_ANSWER]")) {
      state.legacySection = "answer";
      const rest = trimmed.split("[FINAL_ANSWER]").slice(1).join("[FINAL_ANSWER]").trimStart();
      if (rest) emitAnswerChunk(`${rest}\n`);
      return;
    }

    if (trimmed.startsWith("[EXECUTE]")) {
      state.legacySection = "step";
      emitStepLine(trimmed);
      return;
    }

    if (/^\[ReAct-\d+\]/i.test(trimmed)) {
      state.legacySection = "react";
      emitReactLine(trimmed);
      return;
    }

    if (state.legacySection === "plan") {
      emitPlanLine(trimmed);
      return;
    }
    if (state.legacySection === "step") {
      emitStepLine(trimmed);
      return;
    }
    if (state.legacySection === "react") {
      emitReactLine(trimmed);
      return;
    }
    if (state.legacySection === "answer") {
      emitAnswerChunk(`${line}\n`);
      return;
    }

    handlers.onStep?.(trimmed);
  }

  function pushLineBuffer(key, text, onLine) {
    state[key] += text;
    let lineEnd = state[key].indexOf("\n");
    while (lineEnd >= 0) {
      const line = state[key].slice(0, lineEnd);
      state[key] = state[key].slice(lineEnd + 1);
      onLine(line);
      lineEnd = state[key].indexOf("\n");
    }
  }

  function flushLineBuffer(key, onLine) {
    const rest = state[key].trim();
    if (!rest) {
      state[key] = "";
      return;
    }
    onLine(rest);
    state[key] = "";
  }

  function emitPlanLine(line) {
    const raw = String(line || "").replace(/\[PLAN\]/gi, "").trim();
    if (!raw) return;
    const cleaned = raw.replace(/^\d+[\.\)]\s*/, "").trim();
    if (!cleaned) return;
    handlers.onPlan?.(cleaned);
  }

  function emitStepLine(line) {
    const cleaned = String(line || "").replace(/\[EXECUTE\]/gi, "").trim();
    if (!cleaned) return;
    handlers.onStep?.(cleaned);
  }

  function emitReactLine(line) {
    const cleaned = String(line || "").trim();
    if (!cleaned) return;

    const match = cleaned.match(/^\[ReAct-(\d+)\]\s*(Thought|Action|Observation):\s*(.*)$/i);
    if (!match) {
      handlers.onStep?.(cleaned);
      return;
    }

    handlers.onReact?.({
      index: Number.parseInt(match[1], 10),
      field: match[2].toLowerCase(),
      value: match[3] || "",
    });
  }

  function pushAnswerText(text) {
    state.answerBuffer += String(text || "");

    if (!state.answerStarted) {
      const marker = state.answerBuffer.indexOf("[FINAL_ANSWER]");
      if (marker >= 0) {
        state.answerBuffer = state.answerBuffer.slice(marker + "[FINAL_ANSWER]".length);
        state.answerStarted = true;
      } else if (state.answerBuffer.length > 40) {
        state.answerStarted = true;
      } else {
        return;
      }
    }

    emitAnswerChunk(state.answerBuffer);
    state.answerBuffer = "";
  }

  function emitAnswerChunk(chunk) {
    const cleaned = String(chunk || "")
      .replace(/\[FINAL_ANSWER\]/gi, "")
      .replace(/\[DONE\]/gi, "");
    if (!cleaned) return;
    handlers.onAnswer?.(cleaned);
  }

  function tryParseJson(input) {
    try {
      return JSON.parse(String(input));
    } catch {
      return null;
    }
  }

  function safeObject(value, fallback) {
    if (value && typeof value === "object") return value;
    return fallback;
  }

  return {
    reset,
    flush,
    handleSseEvent,
  };
}
