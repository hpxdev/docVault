"""Structured-output schemas sent to the model (OpenAI strict JSON schema: every field required).

Constraints such as list lengths and allowed enum values are stated in descriptions and
enforced server-side after parsing (see `services/insights.py`), so a non-conforming value is
counted and dropped rather than failing the whole call.
"""

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = (
    "contract",
    "report",
    "policy",
    "manual",
    "research",
    "financial",
    "correspondence",
    "resume",
    "other",
)
SENTIMENTS = ("positive", "neutral", "negative", "mixed")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyPointLLM(_Strict):
    text: str = Field(description="One factual point stated in the document")
    refs: list[int] = Field(
        description="Numbers of the [Page N] or [Section N] markers this point comes from"
    )


class EntitiesLLM(_Strict):
    people: list[str]
    organizations: list[str]
    locations: list[str]
    dates: list[str]
    amounts: list[str] = Field(description="Money amounts, quantities and percentages, verbatim")


class SentimentLLM(_Strict):
    label: str = Field(description="One of: positive, neutral, negative, mixed")
    rationale: str = Field(description="One sentence explaining the label")


class DocumentInsightsLLM(_Strict):
    summary_short: str = Field(description="At most 60 words")
    summary_detailed: str = Field(description="At most 250 words")
    key_points: list[KeyPointLLM] = Field(description="5 to 10 points spread across the document")
    entities: EntitiesLLM
    topics: list[str]
    category: str = Field(description="One of: " + ", ".join(CATEGORIES))
    tags: list[str] = Field(description="At most 8 short lowercase tags")
    sentiment: SentimentLLM
    suggested_questions: list[str] = Field(
        description="3 to 5 questions a reader could ask that the document answers"
    )


class SectionNotesLLM(_Strict):
    key_points: list[KeyPointLLM] = Field(description="Up to 6 points covering this section group")
    entities: EntitiesLLM
    figures: list[str] = Field(description="Notable numbers with their context, verbatim")
