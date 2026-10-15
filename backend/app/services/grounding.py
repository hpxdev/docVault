"""Literal evidence checks, not a semantic entailment classifier."""


def normalise_passage(text: str) -> str:
    return " ".join(text.split()).casefold()


def contains_passage(text: str, passage: str) -> bool:
    needle = normalise_passage(passage)
    return bool(needle) and needle in normalise_passage(text)
