import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.available = bool(settings.openai_api_key)
        self.mode = self._detect_mode() if self.available else "dummy"

        self.client: AsyncOpenAI | None = None
        if self.available:
            kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self.client = AsyncOpenAI(**kwargs)
            logger.info("LLM mode=%s, model=%s, base_url=%s", self.mode, settings.openai_model, settings.openai_base_url or "default")
        else:
            logger.warning("LLM mode=dummy (OPENAI_API_KEY not set)")

    def _detect_mode(self) -> str:
        base_url = (self.settings.openai_base_url or "").lower()
        if "dashscope.aliyuncs.com" in base_url:
            return "dashscope"
        return "openai"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        if not self.available or self.client is None:
            return {"content": "", "tool_calls": [], "raw": {}}

        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice if tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        msg = response.choices[0].message

        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )

        return {
            "content": msg.content or "",
            "tool_calls": tool_calls,
            "raw": response.model_dump(),
        }

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not self.available or self.client is None:
            raise RuntimeError("Embedding unavailable without OPENAI_API_KEY")
        response = await self.client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]
