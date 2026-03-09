from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=10)
    use_tools: bool = Field(default=True)
    show_debug: bool = Field(default=False)


class IngestRequest(BaseModel):
    file_path: str = Field(default="data/faq.md")
