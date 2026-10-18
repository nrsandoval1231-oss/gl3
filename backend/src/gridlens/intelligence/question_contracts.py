"""Stable commercial questions mapped to the existing research categories."""

from typing import Any, TypedDict, cast

VERSION = "commercial-questions-v1"


class QuestionContract(TypedDict):
    version: str
    category: str
    question: str


QUESTION_CONTRACTS: dict[str, QuestionContract] = {
    "UTILITY_ONLINE_DATE": {
        "version": VERSION,
        "category": "supply",
        "question": (
            "What dated evidence establishes when utility service will be online "
            "for this exact need?"
        ),
    },
    "TEMP_LOAD_MW": {
        "version": VERSION,
        "category": "load",
        "question": "What exact-need evidence establishes temporary electrical load in MW?",
    },
    "CONSTRUCTION_START": {
        "version": VERSION,
        "category": "timing",
        "question": "What dated evidence establishes construction start for this exact activity?",
    },
    "COMMISSIONING_WINDOW": {
        "version": VERSION,
        "category": "commissioning",
        "question": (
            "What dated evidence establishes commissioning or test-power timing "
            "for this exact need?"
        ),
    },
    "NATURAL_GAS_AVAILABILITY": {
        "version": VERSION,
        "category": "supply",
        "question": (
            "What evidence establishes natural-gas availability and suitability at this exact site?"
        ),
    },
    "DIRECT_BUYER_AUTHORITY": {
        "version": VERSION,
        "category": "buyer",
        "question": (
            "What evidence identifies the direct buyer and establishes purchasing authority?"
        ),
    },
}


def question_contract(question_id: str) -> QuestionContract:
    """Return a fresh contract mapping; unknown IDs fail closed."""
    try:
        return cast(QuestionContract, dict(QUESTION_CONTRACTS[question_id]))
    except KeyError as exc:
        raise ValueError(f"Unknown commercial question: {question_id}") from exc


def question_category(question_id: str) -> str:
    return question_contract(question_id)["category"]


def question_context(question_id: str, context: dict[str, Any]) -> dict[str, Any]:
    """Bind need-specific context to a stable question ID and contract version."""
    contract = question_contract(question_id)
    return {
        "question_id": question_id,
        "contract_version": contract["version"],
        "category": contract["category"],
        "question": contract["question"],
        "context": dict(context),
    }
