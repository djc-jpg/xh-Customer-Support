from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.agents import ExecutorAgent, IntentSentimentAgent, KnowledgeAgent, PlannerAgent
from app.llm import LLMClient
from app.logging_utils import get_trace_logger
from app.memory import SessionMemory
from app.prompt_manager import PromptManager
from app.tool_registry import ToolRegistry


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        memory: SessionMemory,
        prompt_manager: PromptManager,
        tool_registry: ToolRegistry,
        intent_agent: IntentSentimentAgent,
        knowledge_agent: KnowledgeAgent,
        planner_agent: PlannerAgent,
        executor_agent: ExecutorAgent,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.prompt_manager = prompt_manager
        self.tool_registry = tool_registry
        self.intent_agent = intent_agent
        self.knowledge_agent = knowledge_agent
        self.planner_agent = planner_agent
        self.executor_agent = executor_agent

    def begin_trace(self, session_id: str, message: str, top_k: int) -> dict[str, Any]:
        trace_id = f"trace-{uuid4()}"
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_perf = perf_counter()
        trace_logger = get_trace_logger("app.runtime", trace_id)
        trace_logger.info("turn start session=%s top_k=%s message=%s", session_id, top_k, message)
        return {
            "trace_id": trace_id,
            "started_at": started_at,
            "started_perf": started_perf,
            "logger": trace_logger,
        }

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        return self.memory.get_history(session_id)

    def get_memory_snapshot(self, session_id: str) -> dict[str, Any]:
        return self.memory.get_memory_snapshot(session_id)

    async def analyze(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None,
        trace_id: str,
    ) -> dict[str, Any]:
        logger = get_trace_logger("app.runtime.analysis", trace_id)
        logger.info("analysis start session=%s history_len=%s", session_id, len(history))
        result = await self.intent_agent.run(message, history, memory_snapshot=memory_snapshot)
        logger.info("analysis done intent=%s sentiment=%s urgency=%s", result.get("intent"), result.get("sentiment"), result.get("urgency"))
        return result

    async def retrieve(
        self,
        intent: str,
        message: str,
        top_k: int,
        trace_id: str,
    ) -> dict[str, Any]:
        logger = get_trace_logger("app.runtime.knowledge", trace_id)
        logger.info("retrieval start intent=%s top_k=%s", intent, top_k)
        result = await self.knowledge_agent.run(intent, message, top_k=top_k)
        logger.info("retrieval done hit_count=%s", len(result.get("retrieval_docs", [])))
        return result

    async def plan(
        self,
        message: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        use_tools: bool,
        memory_snapshot: dict[str, Any] | None,
        trace_id: str,
    ) -> list[str]:
        logger = get_trace_logger("app.runtime.plan", trace_id)
        logger.info("plan start use_tools=%s", use_tools)
        result = await self.planner_agent.run(
            message,
            analysis,
            knowledge_result,
            use_tools=use_tools,
            memory_snapshot=memory_snapshot,
        )
        logger.info("plan done steps=%s", len(result))
        return result

    async def execute(
        self,
        message: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        plan: list[str],
        history: list[dict[str, Any]],
        use_tools: bool,
        memory_snapshot: dict[str, Any] | None,
        trace_id: str,
    ) -> dict[str, Any]:
        logger = get_trace_logger("app.runtime.execute", trace_id)
        logger.info("execute start use_tools=%s", use_tools)
        result = await self.executor_agent.run(
            message=message,
            analysis=analysis,
            knowledge_result=knowledge_result,
            plan=plan,
            history=history,
            use_tools=use_tools,
            memory_snapshot=memory_snapshot,
        )
        logger.info("execute done tool_calls=%s", len(result.get("tool_outputs", [])))
        return result

    def commit_memory(
        self,
        session_id: str,
        user_message: str,
        final_answer: str,
        analysis: dict[str, Any],
        tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.memory.append_user(session_id, user_message)
        self.memory.append_assistant(session_id, final_answer)
        self.memory.remember_turn(
            session_id=session_id,
            user_message=user_message,
            assistant_message=final_answer,
            analysis=analysis,
            tool_outputs=tool_outputs,
        )
        return self.memory.get_memory_snapshot(session_id)

    def build_trace(
        self,
        trace_id: str,
        session_id: str,
        started_at: str,
        started_perf: float,
        user_input: str,
        top_k: int,
        analysis: dict[str, Any],
        retrieval_hits: list[dict[str, Any]],
        plan_steps: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        final_answer: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "session_id": session_id,
            "timestamp": started_at,
            "llm": {
                "mode": self.llm.mode,
                "model": self.llm.settings.openai_model,
            },
            "user_input": user_input,
            "analysis": analysis,
            "retrieval": {
                "query": f"{analysis.get('intent', 'general_query')}\n{user_input}" if analysis else "",
                "top_k": top_k,
                "hits": retrieval_hits,
            },
            "plan": plan_steps,
            "tool_calls": tool_calls,
            "final_answer": final_answer,
            "latency_ms": int((perf_counter() - started_perf) * 1000),
            "status": status,
        }
        if error:
            payload["error"] = error
        return payload

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "llm_mode": self.llm.mode,
            "agents": [
                {
                    "name": "IntentSentimentAgent",
                    "role": "意图识别、情绪分析、是否需要工具调用",
                },
                {
                    "name": "KnowledgeAgent",
                    "role": "FAQ/RAG 检索与答案草稿生成",
                },
                {
                    "name": "PlannerAgent",
                    "role": "生成可解释执行计划",
                },
                {
                    "name": "ExecutorAgent",
                    "role": "执行计划、调用工具、产出最终回复",
                },
            ],
            "tools": self.tool_registry.describe(),
            "prompts": self.prompt_manager.list_templates(),
            "memory": {
                "type": "in_memory_session_store",
                "features": ["short_history", "facts", "session_summary"],
            },
        }
