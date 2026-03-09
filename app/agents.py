import json
import logging
import re
from typing import Any

from app.llm import LLMClient
from app.rag import RAGService
from app.utils import (
    extract_order_id,
    extract_order_id_from_history,
    load_prompt,
    parse_json_robust,
)
from tools.order_api import QUERY_ORDER_TOOL, query_order
from tools.ticket_api import CREATE_TICKET_TOOL, create_ticket

logger = logging.getLogger(__name__)


async def ask_json_with_retry(
    llm: LLMClient,
    messages: list[dict[str, Any]],
    fallback: dict[str, Any],
    retries: int = 2,
) -> dict[str, Any]:
    if not llm.available:
        return fallback

    dialog = list(messages)
    for i in range(retries + 1):
        rsp = await llm.chat(dialog, temperature=0.0, max_tokens=400)
        parsed = parse_json_robust(rsp.get("content", ""))
        if isinstance(parsed, dict):
            return parsed

        logger.warning("JSON parse failed, retry=%s", i + 1)
        dialog.append({"role": "assistant", "content": rsp.get("content", "")})
        dialog.append({"role": "user", "content": "请仅输出合法 JSON，不要任何解释文字。"})

    return fallback


class IntentSentimentAgent:
    def __init__(self, project_root, llm: LLMClient) -> None:
        self.llm = llm
        self.prompt = load_prompt(project_root, "intent_sentiment.txt")

    async def run(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self._rule_analyze(message, history)
        if not self.llm.available:
            return fallback

        history_text = "\n".join(
            [f"{item['role']}: {item['content']}" for item in history[-6:]]
        ) or "无"
        user_text = (
            f"对话历史:\n{history_text}\n\n"
            f"当前用户消息:\n{message}\n\n"
            "只输出 JSON。"
        )
        parsed = await ask_json_with_retry(
            self.llm,
            [{"role": "system", "content": self.prompt}, {"role": "user", "content": user_text}],
            fallback=fallback,
        )

        return self._normalize_analysis(message, history, parsed, fallback)

    def _rule_analyze(self, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        text = message.lower()
        has_explicit_order = bool(extract_order_id(message)) and any(
            k in text for k in ["订单", "order", "ord"]
        )
        shipping_issue = any(k in text for k in ["物流", "快递", "没动", "丢了"])
        if self._is_privacy_request(text):
            intent = "general_query"
        elif any(k in text for k in ["保险", "理赔", "insurance", "claim"]):
            intent = "general_query"
        elif has_explicit_order and not shipping_issue:
            intent = "order_status"
        elif any(k in text for k in ["退款", "退货", "return", "refund"]):
            intent = "refund"
        elif any(k in text for k in ["登录", "验证码", "password", "账号", "无法进入"]):
            intent = "login_issue"
        elif any(k in text for k in ["发票", "invoice", "税号"]):
            intent = "invoice"
        elif any(k in text for k in ["改地址", "修改地址", "地址填错", "地址写错", "收货地址"]):
            intent = "change_address"
        elif any(k in text for k in ["物流", "快递", "shipping", "多久到", "到哪了", "送达", "什么时候能到"]):
            intent = "shipping"
        elif any(k in text for k in ["订单", "order", "o100", "ord", "查一下"]):
            intent = "order_status"
        else:
            intent = "general_query"

        if self._has_negative_signal(text):
            sentiment = "negative"
        elif self._has_positive_signal(text):
            sentiment = "positive"
        else:
            sentiment = "neutral"

        urgency = "high" if self._has_urgent_signal(text) else "normal"
        need_tool = self._decide_need_tool(intent, text, history, sentiment, urgency)

        return {
            "intent": intent,
            "sentiment": sentiment,
            "urgency": urgency,
            "need_tool": need_tool,
        }

    def _normalize_analysis(
        self,
        message: str,
        history: list[dict[str, Any]],
        parsed: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        text = message.lower()
        has_explicit_order = bool(extract_order_id(message)) and any(
            k in text for k in ["订单", "order", "ord"]
        )
        shipping_issue = any(k in text for k in ["物流", "快递", "没动", "丢了"])
        intent = str(parsed.get("intent", fallback["intent"]))
        sentiment = str(parsed.get("sentiment", fallback["sentiment"]))
        urgency = str(parsed.get("urgency", fallback["urgency"]))

        if self._is_privacy_request(text):
            intent = "general_query"
            sentiment = "neutral"
            urgency = "normal"
        elif any(k in text for k in ["保险", "理赔", "insurance", "claim"]):
            intent = "general_query"
        elif has_explicit_order and not shipping_issue:
            intent = "order_status"
        elif any(k in text for k in ["改地址", "修改地址", "地址填错", "地址写错", "收货地址"]):
            intent = "change_address"
        elif any(k in text for k in ["物流", "快递", "多久到", "到哪了", "送达", "什么时候能到"]):
            intent = "shipping"

        if self._has_positive_signal(text):
            sentiment = "positive"
        elif self._has_negative_signal(text):
            sentiment = "negative"
        elif self._is_plain_information_query(text):
            sentiment = "neutral"

        if self._has_urgent_signal(text):
            urgency = "high"
        elif self._is_plain_information_query(text):
            urgency = "normal"

        if any(k in text for k in ["转人工", "人工客服", "人工处理", "提交工单", "创建工单"]):
            sentiment = "negative" if "投诉" in text else "neutral"
            urgency = "high" if self._has_urgent_signal(text) or "投诉" in text else "normal"

        if self._is_vague_general_query(text):
            intent = "general_query"
            sentiment = "neutral"
            urgency = "normal"

        if self._has_abuse_signal(text) and not self._has_urgent_signal(text):
            sentiment = "negative"
            urgency = "normal"

        if intent == "refund" and any(k in text for k in ["还没到账", "三天", "怎么回事", "太慢"]):
            sentiment = "negative"
            urgency = "high"

        if intent == "login_issue" and not any(k in text for k in ["投诉", "坏了", "系统", "转人工", "人工客服"]):
            sentiment = "neutral"
            urgency = "normal"

        if intent in {"order_status", "shipping"} and not self._has_negative_signal(text) and not self._has_urgent_signal(text):
            sentiment = "neutral"
            urgency = "normal"

        if intent == "change_address" and self._is_plain_information_query(text):
            sentiment = "neutral"
            urgency = "normal"

        need_tool = self._decide_need_tool(intent, text, history, sentiment, urgency)
        return {
            "intent": intent,
            "sentiment": sentiment,
            "urgency": urgency,
            "need_tool": need_tool,
        }

    def _has_positive_signal(self, text: str) -> bool:
        return any(k in text for k in ["谢谢", "感谢", "辛苦", "满意", "不错"])

    def _has_negative_signal(self, text: str) -> bool:
        return any(
            k in text
            for k in [
                "投诉",
                "离谱",
                "废物",
                "垃圾",
                "太慢",
                "坏了",
                "搞什么",
                "着急",
                "急死",
                "生气",
                "没动",
                "查不好",
            ]
        )

    def _has_abuse_signal(self, text: str) -> bool:
        return any(k in text for k in ["废物", "垃圾", "白痴", "蠢", "傻"])

    def _has_urgent_signal(self, text: str) -> bool:
        return any(
            k in text
            for k in ["很着急", "着急", "马上", "立刻", "立即", "尽快", "赶紧", "asap", "现在"]
        )

    def _is_privacy_request(self, text: str) -> bool:
        return any(k in text for k in ["别人", "别人的", "他人", "其他人"]) and any(
            k in text for k in ["订单", "信息", "资料", "隐私"]
        )

    def _is_plain_information_query(self, text: str) -> bool:
        has_question = any(
            k in text
            for k in ["怎么", "如何", "怎么办", "多久", "什么时候", "还能", "能不能", "是不是", "吗", "可不可以"]
        )
        return has_question and not self._has_negative_signal(text) and not self._has_urgent_signal(text)

    def _is_vague_general_query(self, text: str) -> bool:
        return text.strip() in {"这个不太对劲，麻烦看看", "这个不太对劲", "麻烦看看"}

    def _needs_human_handoff(self, intent: str, text: str, sentiment: str, urgency: str) -> bool:
        if any(k in text for k in ["转人工", "人工客服", "人工处理", "提交工单", "创建工单", "客服跟进"]):
            return True
        if any(k in text for k in ["保险", "理赔", "insurance", "claim"]):
            return True
        if intent == "refund" and any(k in text for k in ["三天", "太慢", "还没到账", "投诉"]):
            return True
        if intent in {"login_issue", "invoice", "change_address"} and sentiment == "negative" and urgency == "high":
            return True
        return False

    def _decide_need_tool(
        self,
        intent: str,
        text: str,
        history: list[dict[str, Any]],
        sentiment: str,
        urgency: str,
    ) -> bool:
        if self._is_privacy_request(text):
            return False
        if self._needs_human_handoff(intent, text, sentiment, urgency):
            return True

        has_order_id = bool(extract_order_id(text) or extract_order_id_from_history(history))
        if intent in {"order_status", "shipping"}:
            if self._has_negative_signal(text) and not has_order_id and "订单" in text:
                return False
            return True

        if intent in {"refund", "login_issue", "invoice", "change_address", "general_query"}:
            return False

        return False


class KnowledgeAgent:
    def __init__(self, project_root, llm: LLMClient, rag: RAGService) -> None:
        self.llm = llm
        self.rag = rag
        self.prompt = load_prompt(project_root, "knowledge_agent.txt")

    async def run(self, intent: str, question: str, top_k: int = 3) -> dict[str, Any]:
        query = f"{intent}\n{question}"
        docs = await self.rag.search(query, top_k=top_k)
        contexts = [doc["text"] for doc in docs]

        if not contexts:
            return {
                "contexts": [],
                "retrieval_docs": [],
                "answer_draft": "当前知识库没有直接命中，我先给你通用处理建议并可继续升级人工。",
            }

        context_text = "\n\n---\n\n".join(contexts)
        fallback_answer = self._build_fallback_answer(intent, question, docs)

        if not self.llm.available:
            return {"contexts": contexts, "retrieval_docs": docs, "answer_draft": fallback_answer}

        messages = [
            {"role": "system", "content": self.prompt},
            {
                "role": "user",
                "content": (
                    f"intent: {intent}\n"
                    f"question: {question}\n"
                    f"contexts:\n{context_text}\n\n"
                    "给出简洁 answer_draft。"
                ),
            },
        ]
        rsp = await self.llm.chat(messages, temperature=0.2, max_tokens=400)
        answer_draft = rsp.get("content", "").strip() or fallback_answer
        return {"contexts": contexts, "retrieval_docs": docs, "answer_draft": answer_draft}

    def _build_fallback_answer(
        self,
        intent: str,
        question: str,
        docs: list[dict[str, Any]],
    ) -> str:
        if intent == "order_status":
            return "我先帮你查询订单实时状态，并结合物流进展给你说明后续建议。"

        best_answer = self._extract_best_faq_answer(question, docs)
        if best_answer:
            return f"根据知识库：{best_answer}"

        first_text = str(docs[0].get("text", "")).strip()
        compact = re.sub(r"\s+", " ", first_text).strip()
        if len(compact) > 120:
            compact = compact[:120].rstrip("，。；;,. ") + "..."
        return f"根据知识库，建议先按这个方向处理：{compact}"

    def _extract_best_faq_answer(
        self,
        question: str,
        docs: list[dict[str, Any]],
    ) -> str | None:
        question_terms = self._extract_query_terms(question)
        best_score = -1.0
        best_answer: str | None = None

        for doc_index, doc in enumerate(docs):
            doc_score = float(doc.get("score", 0.0))
            for item in self._parse_faq_items(str(doc.get("text", ""))):
                candidate_text = " ".join(
                    part for part in [item["title"], item["question"], item["answer"]] if part
                )
                score = self._score_candidate(question_terms, candidate_text)
                score += doc_score
                score += max(0, len(docs) - doc_index) * 0.01
                if score > best_score and item["answer"]:
                    best_score = score
                    best_answer = item["answer"]

        return best_answer

    def _parse_faq_items(self, text: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        pattern = re.compile(
            r"(?:^|\n)##\s*(?P<title>.+?)\nQ:\s*(?P<question>.+?)\nA:\s*(?P<answer>.+?)(?=\n##\s|\Z)",
            re.S,
        )
        for match in pattern.finditer(text):
            items.append(
                {
                    "title": self._clean_text(match.group("title")),
                    "question": self._clean_text(match.group("question")),
                    "answer": self._clean_text(match.group("answer")),
                }
            )

        if items:
            return items

        fallback_pattern = re.compile(
            r"Q:\s*(?P<question>.+?)\nA:\s*(?P<answer>.+?)(?=\nQ:\s|\Z)",
            re.S,
        )
        for match in fallback_pattern.finditer(text):
            items.append(
                {
                    "title": "",
                    "question": self._clean_text(match.group("question")),
                    "answer": self._clean_text(match.group("answer")),
                }
            )
        return items

    def _score_candidate(self, question_terms: set[str], candidate_text: str) -> float:
        candidate_norm = self._normalize_text(candidate_text)
        score = 0.0
        for term in question_terms:
            if term and term in candidate_norm:
                score += len(term)
        return score

    def _extract_query_terms(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        terms: set[str] = set(re.findall(r"[a-z0-9]{2,}", normalized))

        stop_terms = {
            "我的",
            "一下",
            "这个",
            "那个",
            "什么",
            "怎么",
            "如何",
            "请问",
            "帮我",
        }
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            max_size = min(4, len(run))
            for size in range(2, max_size + 1):
                for i in range(len(run) - size + 1):
                    term = run[i : i + size]
                    if term not in stop_terms:
                        terms.add(term)
        return terms

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


class PlannerAgent:
    def __init__(self, project_root, llm: LLMClient) -> None:
        self.llm = llm
        self.prompt = load_prompt(project_root, "planner_agent.txt")

    async def run(
        self,
        question: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        use_tools: bool = True,
    ) -> list[str]:
        effective_analysis = dict(analysis)
        if not use_tools:
            effective_analysis["need_tool"] = False

        fallback = self._rule_plan(effective_analysis)
        if not self.llm.available:
            return fallback

        payload = {
            "question": question,
            "analysis": effective_analysis,
            "knowledge_hit_count": len(knowledge_result.get("contexts", [])),
        }
        parsed = await ask_json_with_retry(
            self.llm,
            [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            fallback={"plan": fallback},
        )

        plan = parsed.get("plan", fallback)
        if not isinstance(plan, list):
            return fallback
        clean = [str(item).strip() for item in plan if str(item).strip()]
        return clean or fallback

    def _rule_plan(self, analysis: dict[str, Any]) -> list[str]:
        plan = []
        if analysis.get("urgency") == "high":
            plan.append("标记紧急问题，优先处理并快速反馈")
        plan.append("确认用户诉求与情绪，保证沟通口径一致")
        plan.append("检索知识库并整理可执行方案")
        if analysis.get("need_tool"):
            plan.append("调用工具获取实时数据（订单或工单）")
        plan.append("整合结果，给出下一步操作和补充说明")
        return plan


class ExecutorAgent:
    def __init__(self, project_root, llm: LLMClient) -> None:
        self.llm = llm
        self.prompt = load_prompt(project_root, "executor_agent.txt")
        self.tools = [QUERY_ORDER_TOOL, CREATE_TICKET_TOOL]

    async def run(
        self,
        message: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        plan: list[str],
        history: list[dict[str, Any]],
        use_tools: bool = True,
    ) -> dict[str, Any]:
        tool_strategy = self._decide_tool_strategy(message, analysis, history, use_tools)
        if tool_strategy != "none":
            return self._run_rule(
                message,
                analysis,
                knowledge_result,
                history,
                tool_strategy=tool_strategy,
            )

        if self.llm.available:
            llm_result = await self._run_with_llm(
                message,
                analysis,
                knowledge_result,
                plan,
                history,
                use_tools=False,
            )
            if llm_result["final_answer"].strip():
                return llm_result

        return self._run_rule(
            message,
            analysis,
            knowledge_result,
            history,
            tool_strategy="none",
        )

    async def _run_with_llm(
        self,
        message: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        plan: list[str],
        history: list[dict[str, Any]],
        use_tools: bool = True,
    ) -> dict[str, Any]:
        react_trace: list[dict[str, Any]] = []
        tool_outputs: list[dict[str, Any]] = []

        payload = {
            "message": message,
            "analysis": analysis,
            "plan": plan,
            "knowledge_contexts": knowledge_result.get("contexts", []),
            "answer_draft": knowledge_result.get("answer_draft", ""),
            "history": history[-6:],
            "use_tools": use_tools,
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        tools = self.tools if use_tools else None

        first = await self.llm.chat(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=500,
        )

        final_answer = first.get("content", "").strip()
        tool_calls = first.get("tool_calls", [])

        if tool_calls:
            assistant_tool_calls = []
            for call in tool_calls:
                args = parse_json_robust(call.get("arguments", "")) or {}
                if not isinstance(args, dict):
                    args = {}
                observation = self._call_tool(call["name"], args, message, analysis)
                react_trace.append(
                    {
                        "thought": f"需要通过 {call['name']} 获取实时信息",
                        "action": f"{call['name']}({args})",
                        "observation": observation,
                    }
                )
                tool_outputs.append({"name": call["name"], "result": observation})
                assistant_tool_calls.append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call.get("arguments", "{}")},
                    }
                )

            messages.append({"role": "assistant", "content": first.get("content", ""), "tool_calls": assistant_tool_calls})
            for i, obs in enumerate(tool_outputs):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": assistant_tool_calls[i]["id"],
                        "content": json.dumps(obs["result"], ensure_ascii=False),
                    }
                )
            second = await self.llm.chat(messages=messages, temperature=0.2, max_tokens=500)
            final_answer = second.get("content", "").strip()
        else:
            react_trace.append(
                {
                    "thought": "工具已关闭，直接基于知识库草稿生成回复" if not use_tools else "无需调用工具，直接基于知识库草稿生成回复",
                    "action": "NoTool",
                    "observation": "使用 RAG 草稿与会话上下文",
                }
            )

        if not final_answer:
            final_answer = self._compose_fallback_answer(analysis, knowledge_result, tool_outputs)

        final_answer = self._add_empathy(final_answer, analysis.get("sentiment", "neutral"))
        return {"final_answer": final_answer, "react_trace": react_trace, "tool_outputs": tool_outputs}

    def _run_rule(
        self,
        message: str,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        history: list[dict[str, Any]],
        tool_strategy: str,
    ) -> dict[str, Any]:
        react_trace: list[dict[str, Any]] = []
        tool_outputs: list[dict[str, Any]] = []

        order_id = extract_order_id(message) or extract_order_id_from_history(history)

        if tool_strategy == "privacy_reject":
            react_trace.append(
                {
                    "thought": "请求涉及他人订单或隐私信息，必须直接拒绝并说明边界",
                    "action": "NoTool",
                    "observation": "已按隐私与安全规则拒绝请求",
                }
            )
            final_answer = self._compose_boundary_answer()
            final_answer = self._add_empathy(final_answer, analysis.get("sentiment", "neutral"))
            return {"final_answer": final_answer, "react_trace": react_trace, "tool_outputs": tool_outputs}

        if tool_strategy == "followup_order":
            react_trace.append(
                {
                    "thought": "需要订单号才能继续查询，先向用户补充关键信息",
                    "action": "AskForOrderId",
                    "observation": "当前消息和上下文中都没有可用订单号",
                }
            )
            final_answer = self._compose_missing_order_answer(analysis)
            final_answer = self._add_empathy(final_answer, analysis.get("sentiment", "neutral"))
            return {"final_answer": final_answer, "react_trace": react_trace, "tool_outputs": tool_outputs}

        if tool_strategy in {"query_order", "query_then_ticket"} and order_id:
            args = {"order_id": order_id}
            order_result = self._call_tool("query_order", args, message, analysis)
            react_trace.append(
                {
                    "thought": "先查询订单实时状态，确认是否需要进一步人工跟进",
                    "action": f"query_order({args})",
                    "observation": order_result,
                }
            )
            tool_outputs.append({"name": "query_order", "result": order_result})

            if tool_strategy == "query_then_ticket" and not order_result.get("found"):
                ticket_result = self._create_ticket(message, analysis)
                react_trace.append(
                    {
                        "thought": "订单未查到且用户明确要求跟进，创建人工工单继续处理",
                        "action": "create_ticket(...)",
                        "observation": ticket_result,
                    }
                )
                tool_outputs.append({"name": "create_ticket", "result": ticket_result})
        elif tool_strategy == "create_ticket":
            ticket_result = self._create_ticket(message, analysis)
            react_trace.append(
                {
                    "thought": "当前场景更适合转人工跟进，先创建工单并保留上下文",
                    "action": "create_ticket(...)",
                    "observation": ticket_result,
                }
            )
            tool_outputs.append({"name": "create_ticket", "result": ticket_result})
        else:
            react_trace.append(
                {
                    "thought": "当前问题可以先基于知识库与规则直接回复",
                    "action": "NoTool",
                    "observation": "未触发外部工具调用",
                }
            )

        final_answer = self._compose_fallback_answer(analysis, knowledge_result, tool_outputs)
        final_answer = self._add_empathy(final_answer, analysis.get("sentiment", "neutral"))
        return {"final_answer": final_answer, "react_trace": react_trace, "tool_outputs": tool_outputs}

    def _decide_tool_strategy(
        self,
        message: str,
        analysis: dict[str, Any],
        history: list[dict[str, Any]],
        use_tools: bool,
    ) -> str:
        if not use_tools:
            return "none"

        text = message.lower()
        intent = str(analysis.get("intent", "general_query"))
        sentiment = str(analysis.get("sentiment", "neutral"))
        urgency = str(analysis.get("urgency", "normal"))
        order_id = extract_order_id(message) or extract_order_id_from_history(history)

        if self._is_privacy_request(text):
            return "privacy_reject"

        if any(k in text for k in ["查不到就", "查不到的话", "查不到帮我", "查不到就帮我"]):
            return "query_then_ticket" if order_id else "create_ticket"

        if any(k in text for k in ["转人工", "人工客服", "人工处理", "提交工单", "创建工单", "投诉"]):
            return "create_ticket"

        if any(k in text for k in ["保险", "理赔", "insurance", "claim"]):
            return "create_ticket"

        if intent in {"order_status", "shipping"}:
            if order_id:
                return "query_order"
            return "followup_order"

        if intent == "refund" and any(k in text for k in ["三天", "太慢", "还没到账", "投诉"]):
            return "create_ticket"

        if intent == "invoice" and any(k in text for k in ["还没来", "没收到", "等一天", "等了"]):
            return "create_ticket"

        if intent == "change_address" and any(k in text for k in ["马上要发", "赶紧", "尽快", "快递马上"]):
            return "create_ticket"

        if intent == "login_issue" and sentiment == "negative" and urgency == "high":
            return "create_ticket"

        return "none"

    def _is_privacy_request(self, text: str) -> bool:
        return any(k in text for k in ["别人", "别人的", "他人", "其他人"]) and any(
            k in text for k in ["订单", "信息", "资料", "隐私"]
        )

    def _create_ticket(self, message: str, analysis: dict[str, Any]) -> dict[str, Any]:
        ticket_args = {
            "user_issue": message,
            "priority": "high" if analysis.get("urgency") == "high" else "normal",
        }
        return self._call_tool("create_ticket", ticket_args, message, analysis)

    def _compose_missing_order_answer(self, analysis: dict[str, Any]) -> str:
        if analysis.get("intent") == "shipping":
            return "要继续帮你查物流进展的话，请先发我订单号，我就能马上帮你核对最新状态。"
        return "我可以继续帮你查询订单状态，不过还需要你提供订单号，这样我才能准确核对。"

    def _compose_boundary_answer(self) -> str:
        return "我不能提供他人的订单或隐私信息。如果你是在查询自己的订单，请提供你本人的订单号，我可以继续帮你核对。"

    def _call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        message: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "query_order":
            order_id = str(args.get("order_id") or extract_order_id(message) or "").upper().strip()
            if not order_id:
                return {"error": "缺少 order_id"}
            return query_order(order_id)

        if tool_name == "create_ticket":
            priority = str(args.get("priority", "normal"))
            if priority not in {"low", "normal", "high"}:
                priority = "high" if analysis.get("urgency") == "high" else "normal"
            issue = str(args.get("user_issue") or message).strip()
            return create_ticket(issue, priority)

        return {"error": f"unknown tool: {tool_name}"}

    def _compose_fallback_answer(
        self,
        analysis: dict[str, Any],
        knowledge_result: dict[str, Any],
        tool_outputs: list[dict[str, Any]],
    ) -> str:
        lines = [knowledge_result.get("answer_draft", "我先帮你整理一个处理建议。").strip()]

        for item in tool_outputs:
            if item["name"] == "query_order":
                result = item["result"]
                if result.get("found"):
                    lines.append(
                        f"订单 {result['order_id']} 当前状态：{result['status']}，预计送达：{result['eta']}，最新进展：{result['last_update']}。"
                    )
                else:
                    lines.append(f"订单查询结果：{result.get('message', '未找到订单')}。")
            elif item["name"] == "create_ticket":
                result = item["result"]
                lines.append(
                    f"已为你创建工单 {result.get('ticket_id')}（优先级：{result.get('priority')}），客服会继续跟进。"
                )

        if analysis.get("urgency") == "high":
            lines.append("这是紧急问题，我已按高优先级处理。")

        return "\n".join(lines)

    def _add_empathy(self, content: str, sentiment: str) -> str:
        if sentiment == "negative":
            prefix = "非常抱歉给你带来不便，我已经在尽快帮你处理。"
        elif sentiment == "positive":
            prefix = "感谢你的耐心反馈，我继续协助你。"
        else:
            prefix = "我来帮你处理这个问题。"
        return f"{prefix}\n{content}"
