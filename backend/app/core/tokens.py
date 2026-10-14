"""Token counting with tiktoken.

- `o200k_base`: gpt-4o-mini (chat prompts, insights budget)
- `cl100k_base`: text-embedding-3-small (chunk sizes, embedding token counts)
"""

from functools import lru_cache

import tiktoken


@lru_cache
def chat_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


@lru_cache
def embedding_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_chat_tokens(text: str) -> int:
    return len(chat_encoding().encode(text, disallowed_special=()))


def count_embedding_tokens(text: str) -> int:
    return len(embedding_encoding().encode(text, disallowed_special=()))
