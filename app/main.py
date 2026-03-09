import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agents import ExecutorAgent, IntentSentimentAgent, KnowledgeAgent, PlannerAgent
from app.config import load_settings
from app.llm import LLMClient
from app.memory import SessionMemory
from app.rag import RAGService
from app.schemas import ChatRequest, IngestRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("app.main")

settings = load_settings()
llm = LLMClient(settings)
memory = SessionMemory(max_turns=settings.memory_turns)
rag = RAGService(settings, llm)

intent_agent = IntentSentimentAgent(settings.project_root, llm)
knowledge_agent = KnowledgeAgent(settings.project_root, llm, rag)
planner_agent = PlannerAgent(settings.project_root, llm)
executor_agent = ExecutorAgent(settings.project_root, llm)

app = FastAPI(title="AI Customer Support Agent Demo", version="0.1.0")
frontend_dir = settings.project_root / "frontend"
if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


def sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def clip_text(text: str, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip("，。；;,. ") + "..."


def build_retrieval_hits(docs: list[dict], top_k: int) -> list[dict]:
    hits: list[dict] = []
    for idx, doc in enumerate(docs[:top_k], start=1):
        hits.append(
            {
                "rank": idx,
                "source": doc.get("metadata", {}).get("source", ""),
                "score": round(float(doc.get("score", 0.0)), 6),
                "snippet": clip_text(doc.get("text", "")),
            }
        )
    return hits


def build_plan_steps(plan: list[str]) -> list[dict]:
    return [
        {
            "step_id": f"s{i + 1}",
            "content": step,
            "requires_tool": "工具" in step or "query_order" in step or "create_ticket" in step,
        }
        for i, step in enumerate(plan)
    ]


def classify_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "tool" in message:
        return "tool_execution_error"
    if "timeout" in message:
        return "unknown_error"
    if "json" in message or "parse" in message:
        return "response_grounding_error"
    return "unknown_error"


async def stream_text(text: str, event_type: str = "token", delay: float = 0.004) -> AsyncGenerator[str, None]:
    for ch in text:
        yield sse_data({"type": event_type, "content": ch})
        if delay > 0:
            await asyncio.sleep(delay)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "llm_mode": llm.mode}


@app.get("/")
async def home():
    if frontend_dir.exists():
        return RedirectResponse(url="/frontend/", status_code=307)

    # Always return a visible fallback page instead of JSON to avoid blank-screen confusion.
    html = """
<!doctype html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>AI 客服 Demo</title></head>
<body style="font-family:Arial,sans-serif;padding:24px;line-height:1.6;">
  <h2>AI 智能客服 Agent</h2>
  <p>前端静态页未找到，请访问 <a href="/health">/health</a> 检查服务状态。</p>
  <p>你也可以把前端文件放到 <code>frontend/index.html</code> 后刷新。</p>
</body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)


@app.get("/styles.css")
async def root_styles():
    css_file = frontend_dir / "styles.css"
    if css_file.exists():
        return FileResponse(css_file, media_type="text/css")
    return HTMLResponse("/* styles.css not found */", media_type="text/css", status_code=404)


@app.get("/app.js")
async def root_app_js():
    js_file = frontend_dir / "app.js"
    if js_file.exists():
        return FileResponse(js_file, media_type="application/javascript")
    return HTMLResponse("// app.js not found", media_type="application/javascript", status_code=404)


@app.get("/ui")
async def ui_fallback() -> HTMLResponse:
    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 客服 UI 回退页</title>
</head>
<body style="font-family:Arial,sans-serif;padding:20px;line-height:1.6;background:#f8fafc;color:#0f172a;">
  <h2>AI 客服 UI 回退页</h2>
  <p>如果 <code>/</code> 页面空白，请先用此页面联调。</p>
  <p><button id="ingest">导入知识库</button></p>
  <p><textarea id="msg" style="width:100%;height:80px;">我很着急，我的订单 O1001 到哪了？</textarea></p>
  <p><button id="send">发送 /chat</button></p>
  <pre id="out" style="white-space:pre-wrap;background:#fff;border:1px solid #ddd;padding:12px;min-height:180px;"></pre>
  <script>
    const out = document.getElementById("out");
    const msg = document.getElementById("msg");
    document.getElementById("ingest").onclick = async () => {
      const r = await fetch("/ingest", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({file_path:"data/faq.md"})});
      out.textContent = JSON.stringify(await r.json(), null, 2);
    };
    document.getElementById("send").onclick = async () => {
      out.textContent = "";
      const r = await fetch("/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({session_id:"demo-ui", message: msg.value})});
      const reader = r.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream:true});
        const blocks = buffer.split("\\n\\n");
        buffer = blocks.pop() || "";
        for (const b of blocks) {
          const line = b.split("\\n").find(x => x.startsWith("data: "));
          if (!line) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") continue;
          try {
            const obj = JSON.parse(payload);
            if (typeof obj.content === "string") out.textContent += obj.content;
            else out.textContent += "\\n" + JSON.stringify(obj.content) + "\\n";
          } catch {
            out.textContent += payload;
          }
        }
      }
    };
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)


@app.get("/ingest")
async def ingest_page() -> HTMLResponse:
    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ingest 知识库</title>
</head>
<body style="font-family:Arial,sans-serif;padding:20px;line-height:1.6;background:#f8fafc;color:#0f172a;">
  <h2>/ingest 页面</h2>
  <p>你当前是浏览器 GET 请求。真正的导入调用是 <code>POST /ingest</code>。</p>
  <p>
    <button id="ingestBtn">立即导入 data/faq.md</button>
    <a href="/" style="margin-left:10px;">返回首页</a>
    <a href="/ui" style="margin-left:10px;">回退 UI</a>
  </p>
  <pre id="result" style="white-space:pre-wrap;background:#fff;border:1px solid #ddd;padding:12px;min-height:120px;"></pre>
  <script>
    const result = document.getElementById("result");
    document.getElementById("ingestBtn").onclick = async () => {
      result.textContent = "导入中...";
      try {
        const resp = await fetch("/ingest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: "data/faq.md" })
        });
        result.textContent = JSON.stringify(await resp.json(), null, 2);
      } catch (e) {
        result.textContent = String(e);
      }
    };
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)


@app.post("/ingest")
async def ingest(req: IngestRequest | None = Body(default=None)) -> dict:
    req = req or IngestRequest()
    result = await rag.ingest_markdown(req.file_path)
    logger.info("ingest completed: %s", result)
    return result


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    async def event_stream() -> AsyncGenerator[str, None]:
        session_id = req.session_id
        message = req.message
        top_k = req.top_k
        use_tools = req.use_tools
        show_debug = req.show_debug
        trace_id = f"trace-{uuid4()}"
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_perf = perf_counter()
        logger.info("chat start session=%s message=%s", session_id, message)
        try:
            history = memory.get_history(session_id)

            analysis = await intent_agent.run(message, history)
            knowledge_result = await knowledge_agent.run(
                analysis.get("intent", "general_query"),
                message,
                top_k=top_k,
            )

            if show_debug:
                for idx, doc in enumerate(knowledge_result.get("retrieval_docs", []), start=1):
                    yield sse_data(
                        {
                            "type": "retrieval",
                            "content": {
                                "rank": idx,
                                "source": doc.get("metadata", {}).get("source", ""),
                                "score": doc.get("score", 0.0),
                                "text": doc.get("text", ""),
                            },
                        }
                    )

            plan = await planner_agent.run(message, analysis, knowledge_result, use_tools=use_tools)

            plan_text = "[PLAN]\n" + "\n".join([f"{i + 1}. {step}" for i, step in enumerate(plan)]) + "\n\n"
            async for event in stream_text(plan_text, event_type="plan"):
                yield event

            for i, step in enumerate(plan):
                execute_line = f"[EXECUTE] Step {i + 1}/{len(plan)}: {step}\n"
                async for event in stream_text(execute_line, event_type="execute", delay=0.001):
                    yield event

            execution = await executor_agent.run(
                message=message,
                analysis=analysis,
                knowledge_result=knowledge_result,
                plan=plan,
                history=history,
                use_tools=use_tools,
            )

            if show_debug:
                for item in execution.get("tool_outputs", []):
                    yield sse_data({"type": "tool", "content": item})

            for idx, trace in enumerate(execution.get("react_trace", []), start=1):
                line = (
                    f"[ReAct-{idx}] Thought: {trace.get('thought')}\n"
                    f"[ReAct-{idx}] Action: {trace.get('action')}\n"
                    f"[ReAct-{idx}] Observation: {trace.get('observation')}\n"
                )
                async for event in stream_text(line, event_type="react", delay=0.001):
                    yield event

            final_answer = execution["final_answer"]
            answer_head = "\n[FINAL_ANSWER]\n"
            async for event in stream_text(answer_head, event_type="answer", delay=0.001):
                yield event
            async for event in stream_text(final_answer, event_type="answer"):
                yield event

            memory.append_user(session_id, message)
            memory.append_assistant(session_id, final_answer)

            retrieval_docs = knowledge_result.get("retrieval_docs", [])
            trace = {
                "trace_id": trace_id,
                "session_id": session_id,
                "timestamp": started_at,
                "llm": {
                    "mode": llm.mode,
                    "model": settings.openai_model,
                },
                "user_input": message,
                "analysis": analysis,
                "retrieval": {
                    "query": f"{analysis.get('intent', 'general_query')}\n{message}",
                    "top_k": top_k,
                    "hits": build_retrieval_hits(retrieval_docs, top_k),
                },
                "plan": build_plan_steps(plan),
                "tool_calls": execution.get("tool_outputs", []),
                "final_answer": final_answer,
                "latency_ms": int((perf_counter() - started_perf) * 1000),
                "status": "success",
            }
            meta = {
                "trace_id": trace_id,
                "analysis": analysis,
                "tool_outputs": execution.get("tool_outputs", []),
                "history_len": len(memory.get_history(session_id)),
                "top_k": top_k,
                "use_tools": use_tools,
                "trace": trace,
            }
            if show_debug:
                meta.update(
                    {
                        "knowledge": knowledge_result,
                        "plan": plan,
                        "react_trace": execution.get("react_trace", []),
                        "retrieval": knowledge_result.get("retrieval_docs", []),
                    }
                )
            yield sse_data({"type": "meta", "content": meta})
            yield "data: [DONE]\n\n"
            logger.info("chat end session=%s", session_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat error session=%s", req.session_id)
            error_type = classify_error(exc)
            trace = {
                "trace_id": trace_id,
                "session_id": session_id,
                "timestamp": started_at,
                "llm": {
                    "mode": llm.mode,
                    "model": settings.openai_model,
                },
                "user_input": message,
                "analysis": {},
                "retrieval": {
                    "query": "",
                    "top_k": top_k,
                    "hits": [],
                },
                "plan": [],
                "tool_calls": [],
                "final_answer": "",
                "latency_ms": int((perf_counter() - started_perf) * 1000),
                "status": "failed",
                "error": {
                    "type": error_type,
                    "message": str(exc),
                },
            }
            error_text = f"[ERROR] {str(exc)}"
            yield sse_data({"type": "meta", "content": {"trace_id": trace_id, "trace": trace}})
            yield sse_data({"type": "error", "content": error_text})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
