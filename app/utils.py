import json
import re
from pathlib import Path
from typing import Any


def load_prompt(project_root: Path, file_name: str) -> str:
    prompt_path = project_root / "prompts" / file_name
    return prompt_path.read_text(encoding="utf-8")


def parse_json_robust(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def split_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    blocks = [blk.strip() for blk in text.split("\n\n") if blk.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(current) + len(block) + 2 <= chunk_size:
            current = f"{current}\n\n{block}".strip()
            continue
        if current:
            chunks.append(current)
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + "\n\n" + block
            else:
                current = block
        else:
            chunks.append(block[:chunk_size])
            current = block[chunk_size - overlap :] if len(block) > chunk_size else ""
    if current:
        chunks.append(current)
    return chunks


def extract_order_id(message: str) -> str | None:
    patterns = [r"\bO\d{4,}\b", r"\bORD\d{4,}\b", r"\b\d{6,}\b"]
    for pattern in patterns:
        matched = re.search(pattern, message.upper())
        if matched:
            return matched.group(0)
    return None


def extract_order_id_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", ""))
        order_id = extract_order_id(content)
        if order_id:
            return order_id
    return None
