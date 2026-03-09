import logging
from typing import Any

from app.agents import ExecutorAgent, IntentSentimentAgent, KnowledgeAgent, PlannerAgent
from app.memory import SessionMemory

logger = logging.getLogger(__name__)


class SupportOrchestrator:
    def __init__(
        self,
        memory: SessionMemory,
        intent_agent: IntentSentimentAgent,
        knowledge_agent: KnowledgeAgent,
        planner_agent: PlannerAgent,
        executor_agent: ExecutorAgent,
    ) -> None:
        self.memory = memory
        self.intent_agent = intent_agent
        self.knowledge_agent = knowledge_agent
        self.planner_agent = planner_agent
        self.executor_agent = executor_agent

    async def process(self, session_id: str, message: str) -> dict[str, Any]:
        history = self.memory.get_history(session_id)
        logger.info("session=%s step=intent", session_id)
        analysis = await self.intent_agent.run(message, history)

        logger.info("session=%s step=knowledge intent=%s", session_id, analysis.get("intent"))
        knowledge_result = await self.knowledge_agent.run(analysis.get("intent", "general_query"), message)

        logger.info("session=%s step=plan", session_id)
        plan = await self.planner_agent.run(message, analysis, knowledge_result)

        logger.info("session=%s step=execute", session_id)
        execution = await self.executor_agent.run(
            message=message,
            analysis=analysis,
            knowledge_result=knowledge_result,
            plan=plan,
            history=history,
        )

        self.memory.append_user(session_id, message)
        self.memory.append_assistant(session_id, execution["final_answer"])

        return {
            "analysis": analysis,
            "knowledge": knowledge_result,
            "plan": plan,
            "execution": execution,
        }

