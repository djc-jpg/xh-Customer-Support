/**
 * 这里封装 /agent/chat 的流式请求：
 * - 必须使用 POST（EventSource 不支持）
 * - 用 ReadableStream 增量读取
 * - 对外只抛出统一的 SSE 事件对象，便于 parser 复用
 */
export function startChatStream({ baseUrl, payload, onEvent }) {
  const controller = new AbortController();

  const done = (async () => {
    const response = await fetch(`${baseUrl}/agent/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`HTTP_${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done: streamDone } = await reader.read();
      if (streamDone) break;

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";

      blocks.forEach((block) => {
        const evt = parseSseBlock(block);
        if (!evt) return;
        onEvent(evt);
      });
    }

    if (buffer.trim()) {
      const tail = parseSseBlock(buffer);
      if (tail) onEvent(tail);
    }
  })();

  return {
    abort: () => controller.abort(),
    done,
  };
}

export function isAbortError(error) {
  return Boolean(error) && (error.name === "AbortError" || String(error).includes("AbortError"));
}

function parseSseBlock(raw) {
  const block = String(raw || "").trim();
  if (!block) return null;

  const lines = block.split("\n");
  let event = "message";
  const dataLines = [];
  let hasSseField = false;

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      hasSseField = true;
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
      hasSseField = true;
    }
  });

  if (!hasSseField) {
    return { event: "message", data: block };
  }

  return {
    event: event || "message",
    data: dataLines.join("\n"),
  };
}
