from dataclasses import dataclass
from pathlib import Path
from string import Template


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    path: Path
    content: str


class PromptManager:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir
        self._cache: dict[str, PromptTemplate] = {}

    def get(self, name: str) -> PromptTemplate:
        if name not in self._cache:
            path = self.prompts_dir / name
            content = path.read_text(encoding="utf-8")
            self._cache[name] = PromptTemplate(name=name, path=path, content=content)
        return self._cache[name]

    def render(self, name: str, **kwargs: str) -> str:
        template = self.get(name)
        if not kwargs:
            return template.content
        return Template(template.content).safe_substitute(**kwargs)

    def list_templates(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for path in sorted(self.prompts_dir.glob("*.txt")):
            items.append(
                {
                    "name": path.name,
                    "path": str(path),
                }
            )
        return items
