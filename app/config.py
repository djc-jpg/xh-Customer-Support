import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DASHSCOPE_BASE_URL_CN = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class Settings:
    project_root: Path
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    embedding_model: str
    chroma_dir: str
    chroma_collection: str
    memory_turns: int
    chunk_size: int
    chunk_overlap: int


def load_settings() -> Settings:
    load_dotenv()
    root = Path(__file__).resolve().parents[1]
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    aliyun_api_key = os.getenv("ALIBABA_CLOUD_API_KEY", "").strip()

    effective_api_key = openai_api_key or dashscope_api_key or aliyun_api_key
    using_dashscope = bool(effective_api_key) and not openai_api_key

    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip() or os.getenv("DASHSCOPE_BASE_URL", "").strip()
    if using_dashscope and not openai_base_url:
        openai_base_url = DASHSCOPE_BASE_URL_CN

    openai_model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("DASHSCOPE_MODEL", "").strip()
    if not openai_model:
        openai_model = "qwen-plus" if using_dashscope else "gpt-4o-mini"

    embedding_model = os.getenv("EMBEDDING_MODEL", "").strip() or os.getenv("DASHSCOPE_EMBEDDING_MODEL", "").strip()
    if not embedding_model:
        embedding_model = "text-embedding-v4" if using_dashscope else "text-embedding-3-small"

    return Settings(
        project_root=root,
        openai_api_key=effective_api_key,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        embedding_model=embedding_model,
        chroma_dir=os.getenv("CHROMA_DIR", "chroma_db").strip(),
        chroma_collection=os.getenv("CHROMA_COLLECTION", "customer_support_faq").strip(),
        memory_turns=int(os.getenv("MEMORY_TURNS", "6")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "500")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "80")),
    )
