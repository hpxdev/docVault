"""Versioned prompt templates (`<name>.md`, sections `## system` and `## user`).

Templates use LangChain f-string syntax: `{variable}`; literal braces must be doubled.
Every stored AI output records the `version` of the template that produced it.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

PROMPT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user: str

    def messages(self, **variables: object) -> list[BaseMessage]:
        template = ChatPromptTemplate.from_messages([("system", self.system), ("human", self.user)])
        return template.format_messages(**variables)


@cache
def load_prompt(version: str) -> Prompt:
    raw = (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.strip() in ("## system", "## user"):
            current = line.strip()[3:]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return Prompt(
        version=version,
        system="\n".join(sections["system"]).strip(),
        user="\n".join(sections["user"]).strip(),
    )
