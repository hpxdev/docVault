"""Human-readable labels for segment/chunk locators (used in prompts and citations)."""

from typing import Any


def locator_label(locator: dict[str, Any] | None) -> str:
    if not locator:
        return "unknown location"
    kind = locator.get("type")
    if kind == "page":
        return f"page {locator.get('page')}"
    if kind == "lines":
        return f"lines {locator.get('start')}-{locator.get('end')}"
    if kind == "section":
        path = locator.get("heading_path") or (
            [locator["heading"]] if locator.get("heading") else []
        )
        if path:
            return f'section "{" > ".join(path)}"'
        return f"section {locator.get('index')} (untitled)"
    return "unknown location"
