/**
 * UI 模块只负责“渲染和交互元素”，不直接处理业务请求。
 * 这样可以把数据流和视图更新解耦，后续更换框架时也更容易迁移。
 */
export function createUI(text) {
  const refs = {
    titleMain: document.getElementById("titleMain"),
    titleSub: document.getElementById("titleSub"),
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),
    statusMode: document.getElementById("statusMode"),
    statusTopK: document.getElementById("statusTopK"),
    statusTools: document.getElementById("statusTools"),

    chatTitle: document.getElementById("chatTitle"),
    chatList: document.getElementById("chatList"),
    messageLabel: document.getElementById("messageLabel"),
    messageInput: document.getElementById("messageInput"),
    composerHint: document.getElementById("composerHint"),
    sendBtn: document.getElementById("sendBtn"),
    stopBtn: document.getElementById("stopBtn"),
    retryBtn: document.getElementById("retryBtn"),

    settingsTitle: document.getElementById("settingsTitle"),
    ingestBtn: document.getElementById("ingestBtn"),
    sessionLabel: document.getElementById("sessionLabel"),
    sessionHistoryLabel: document.getElementById("sessionHistoryLabel"),
    topKLabel: document.getElementById("topKLabel"),
    toolLabel: document.getElementById("toolLabel"),
    toolSwitchText: document.getElementById("toolSwitchText"),
    sessionInput: document.getElementById("sessionInput"),
    sessionSelect: document.getElementById("sessionSelect"),
    topKInput: document.getElementById("topKInput"),
    useToolsInput: document.getElementById("useToolsInput"),
    switchSessionBtn: document.getElementById("switchSessionBtn"),
    clearSessionBtn: document.getElementById("clearSessionBtn"),
    ingestBanner: document.getElementById("ingestBanner"),

    debugTitle: document.getElementById("debugTitle"),
    debugToggleBtn: document.getElementById("debugToggleBtn"),
    debugBody: document.getElementById("debugBody"),
    tabTrace: document.getElementById("tabTrace"),
    tabRetrieval: document.getElementById("tabRetrieval"),
    tabTools: document.getElementById("tabTools"),
    tabRaw: document.getElementById("tabRaw"),
    planTitle: document.getElementById("planTitle"),
    stepsTitle: document.getElementById("stepsTitle"),
    reactTitle: document.getElementById("reactTitle"),
    planList: document.getElementById("planList"),
    stepsList: document.getElementById("stepsList"),
    reactList: document.getElementById("reactList"),
    retrievalList: document.getElementById("retrievalList"),
    toolsList: document.getElementById("toolsList"),
    copyDebugBtn: document.getElementById("copyDebugBtn"),
    rawDebug: document.getElementById("rawDebug"),

    toastContainer: document.getElementById("toastContainer"),
  };

  const state = {
    debugOpen: false,
    activeTab: "trace",
    handlers: null,
  };

  function applyStaticText() {
    document.title = text.documentTitle;

    refs.titleMain.textContent = text.header.title;
    refs.titleSub.textContent = text.header.subtitle;

    refs.chatTitle.textContent = text.chat.title;
    refs.messageLabel.textContent = text.chat.messageLabel;
    refs.messageInput.placeholder = text.chat.messagePlaceholder;
    refs.composerHint.textContent = text.chat.hint;
    refs.sendBtn.textContent = text.chat.send;
    refs.stopBtn.textContent = text.chat.stop;
    refs.retryBtn.textContent = text.chat.retry;

    refs.settingsTitle.textContent = text.settings.title;
    refs.ingestBtn.textContent = text.settings.ingest;
    refs.sessionLabel.textContent = text.settings.sessionId;
    refs.sessionHistoryLabel.textContent = text.settings.sessionHistory;
    refs.topKLabel.textContent = text.settings.topK;
    refs.toolLabel.textContent = text.settings.useTools;
    refs.toolSwitchText.textContent = text.settings.useToolsSwitch;
    refs.switchSessionBtn.textContent = text.settings.switchSession;
    refs.clearSessionBtn.textContent = text.settings.clearSession;

    refs.debugTitle.textContent = text.debug.title;
    refs.tabTrace.textContent = text.debug.tabTrace;
    refs.tabRetrieval.textContent = text.debug.tabRetrieval;
    refs.tabTools.textContent = text.debug.tabTools;
    refs.tabRaw.textContent = text.debug.tabRaw;
    refs.planTitle.textContent = text.debug.planTitle;
    refs.stepsTitle.textContent = text.debug.stepsTitle;
    refs.reactTitle.textContent = text.debug.reactTitle;
    refs.copyDebugBtn.textContent = text.debug.copyRaw;

    updateDebugToggleText();
  }

  function bindEvents(handlers) {
    state.handlers = handlers;

    refs.sendBtn.addEventListener("click", () => handlers.onSend?.());
    refs.stopBtn.addEventListener("click", () => handlers.onStop?.());
    refs.retryBtn.addEventListener("click", () => handlers.onRetry?.());
    refs.ingestBtn.addEventListener("click", () => handlers.onIngest?.());

    refs.switchSessionBtn.addEventListener("click", () => {
      handlers.onSwitchSession?.(refs.sessionInput.value.trim());
    });

    refs.clearSessionBtn.addEventListener("click", () => {
      handlers.onClearSession?.();
    });

    refs.sessionSelect.addEventListener("change", () => {
      handlers.onSessionSelect?.(refs.sessionSelect.value);
    });

    refs.topKInput.addEventListener("change", () => {
      handlers.onSettingsChange?.({
        topK: getTopK(),
        useTools: getUseTools(),
      });
    });

    refs.useToolsInput.addEventListener("change", () => {
      handlers.onSettingsChange?.({
        topK: getTopK(),
        useTools: getUseTools(),
      });
    });

    refs.messageInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handlers.onSend?.();
      }
    });

    refs.chatList.addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      const value = chip.getAttribute("data-value") || "";
      handlers.onQuickChip?.(value);
    });

    refs.debugToggleBtn.addEventListener("click", () => {
      setDebugOpen(!state.debugOpen);
      handlers.onDebugToggle?.(state.debugOpen);
    });

    document.querySelectorAll(".tab").forEach((tabEl) => {
      tabEl.addEventListener("click", () => {
        const tab = tabEl.getAttribute("data-tab");
        setActiveTab(tab || "trace");
        handlers.onTabChange?.(state.activeTab);
      });
    });

    refs.copyDebugBtn.addEventListener("click", () => {
      handlers.onCopyDebug?.(refs.rawDebug.textContent || "{}");
    });
  }

  function setDebugOpen(open) {
    state.debugOpen = !!open;
    refs.debugBody.classList.toggle("is-collapsed", !state.debugOpen);
    updateDebugToggleText();
  }

  function updateDebugToggleText() {
    refs.debugToggleBtn.textContent = state.debugOpen ? text.debug.collapse : text.debug.expand;
  }

  function isDebugOpen() {
    return state.debugOpen;
  }

  function setActiveTab(tab) {
    state.activeTab = tab;

    document.querySelectorAll(".tab").forEach((el) => {
      el.classList.toggle("is-active", el.getAttribute("data-tab") === tab);
    });

    document.querySelectorAll(".tab-panel").forEach((el) => {
      el.classList.toggle("is-active", el.getAttribute("data-panel") === tab);
    });
  }

  function getActiveTab() {
    return state.activeTab;
  }

  function getMessage() {
    return refs.messageInput.value;
  }

  function setMessage(value) {
    refs.messageInput.value = value;
  }

  function clearMessage() {
    refs.messageInput.value = "";
  }

  function focusMessage() {
    refs.messageInput.focus();
  }

  function setSessionInput(value) {
    refs.sessionInput.value = value;
  }

  function renderSessionOptions(ids, currentId) {
    refs.sessionSelect.innerHTML = "";
    ids.forEach((id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      refs.sessionSelect.appendChild(option);
    });
    refs.sessionSelect.value = currentId;
  }

  function getTopK() {
    const value = Number.parseInt(refs.topKInput.value, 10);
    if (Number.isNaN(value)) return 3;
    return Math.min(10, Math.max(1, value));
  }

  function getUseTools() {
    return Boolean(refs.useToolsInput.checked);
  }

  function setSettings({ topK, useTools }) {
    refs.topKInput.value = String(topK);
    refs.useToolsInput.checked = Boolean(useTools);
  }

  /**
   * 顶部状态条只显示“最终状态值”，避免把内部细节暴露给用户。
   */
  function renderStatus(status) {
    refs.statusDot.className = `status-dot is-${status.code}`;
    refs.statusText.textContent = status.label;
    refs.statusMode.textContent = `${text.status.modePrefix}：${status.mode}`;
    refs.statusTopK.textContent = `${text.status.topKPrefix}：${status.topK}`;
    refs.statusTools.textContent = `${text.status.toolsPrefix}：${status.tools}`;
  }

  function renderMessages(messages) {
    refs.chatList.innerHTML = "";

    if (!messages.length) {
      refs.chatList.appendChild(renderEmptyGuide());
      return;
    }

    messages.forEach((item) => {
      const row = document.createElement("article");
      row.className = `message-row ${item.role}`;

      const bubble = document.createElement("div");
      bubble.className = "bubble";

      const content = document.createElement("div");
      content.textContent = item.content;
      bubble.appendChild(content);

      const time = document.createElement("div");
      time.className = "message-time";
      time.textContent = formatTime(item.ts);
      bubble.appendChild(time);

      row.appendChild(bubble);
      refs.chatList.appendChild(row);
    });

    refs.chatList.scrollTo({
      top: refs.chatList.scrollHeight,
      behavior: "smooth",
    });
  }

  function renderEmptyGuide() {
    const wrap = document.createElement("div");
    wrap.className = "empty-guide";

    const card = document.createElement("div");
    card.className = "empty-guide-card";

    const title = document.createElement("h3");
    title.textContent = text.chat.emptyTitle;
    card.appendChild(title);

    const desc = document.createElement("p");
    desc.textContent = text.chat.emptyDesc;
    card.appendChild(desc);

    const chipRow = document.createElement("div");
    chipRow.className = "chip-row";
    text.chat.quickChips.forEach((item) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = item;
      chip.setAttribute("data-value", item);
      chipRow.appendChild(chip);
    });

    card.appendChild(chipRow);
    wrap.appendChild(card);
    return wrap;
  }

  function setStreaming(isStreaming) {
    refs.sendBtn.disabled = isStreaming;
    refs.stopBtn.disabled = !isStreaming;
    refs.retryBtn.disabled = isStreaming;
    refs.ingestBtn.disabled = isStreaming;
  }

  function setIngestBusy(busy) {
    refs.ingestBtn.disabled = busy;
    refs.ingestBtn.textContent = busy ? text.settings.ingestLoading : text.settings.ingest;
  }

  function renderIngestBanner(banner) {
    refs.ingestBanner.className = `ingest-banner ingest-${banner.kind}`;
    refs.ingestBanner.textContent = banner.text;
  }

  /**
   * 调试面板按四个块渲染，确保长文本也能稳定排版。
   */
  function renderDebug(debug) {
    renderList(refs.planList, debug.plan, true);
    renderList(refs.stepsList, debug.steps, false);
    renderReact(refs.reactList, debug.react);
    renderMonoObjects(refs.retrievalList, debug.retrieval);
    renderMonoObjects(refs.toolsList, debug.tools);
    refs.rawDebug.textContent = JSON.stringify(debug.raw ?? {}, null, 2);
  }

  function renderList(container, items, ordered) {
    container.innerHTML = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = text.debug.empty;
      container.appendChild(li);
      return;
    }

    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = String(item);
      container.appendChild(li);
    });

    if (!ordered) {
      container.style.listStyle = "disc";
    }
  }

  function renderReact(container, rows) {
    container.innerHTML = "";
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty-hint";
      empty.textContent = text.debug.empty;
      container.appendChild(empty);
      return;
    }

    rows.forEach((row) => {
      const block = document.createElement("div");
      block.className = "mono-box";

      const lines = [
        `#${row.index}`,
        `${text.debug.reactThought}: ${row.thought || ""}`,
        `${text.debug.reactAction}: ${row.action || ""}`,
        `${text.debug.reactObservation}: ${row.observation || ""}`,
      ];
      block.textContent = lines.join("\n");
      container.appendChild(block);
    });
  }

  function renderMonoObjects(container, list) {
    container.innerHTML = "";
    if (!list.length) {
      const empty = document.createElement("p");
      empty.className = "empty-hint";
      empty.textContent = text.debug.empty;
      container.appendChild(empty);
      return;
    }

    list.forEach((item) => {
      const block = document.createElement("pre");
      block.className = "mono-box";
      block.textContent = JSON.stringify(item, null, 2);
      container.appendChild(block);
    });
  }

  function showToast(type, message) {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    refs.toastContainer.appendChild(toast);

    while (refs.toastContainer.childElementCount > 4) {
      refs.toastContainer.removeChild(refs.toastContainer.firstElementChild);
    }

    window.setTimeout(() => {
      toast.remove();
    }, 2600);
  }

  function formatTime(ts) {
    const date = new Date(ts);
    return date.toLocaleTimeString("zh-CN", { hour12: false });
  }

  return {
    applyStaticText,
    bindEvents,
    setDebugOpen,
    isDebugOpen,
    setActiveTab,
    getActiveTab,
    getMessage,
    setMessage,
    clearMessage,
    focusMessage,
    setSessionInput,
    renderSessionOptions,
    getTopK,
    getUseTools,
    setSettings,
    renderStatus,
    renderMessages,
    setStreaming,
    setIngestBusy,
    renderIngestBanner,
    renderDebug,
    showToast,
  };
}
