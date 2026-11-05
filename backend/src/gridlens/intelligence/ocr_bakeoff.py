"""Internal offline OCR bake-off: precision and recall per dollar on gold-set scan pages.

This harness scores OCR providers on pages whose equipment facts are known. It makes no
network call and has no live adapter. A provider is anything that implements ``OcrProvider``;
the three shipped ones (OpenAI vision, Amazon Textract, Mistral OCR) replay transcripts the
owner recorded earlier, so a run is repeatable and free.

Scoring runs each provider's text through the same deterministic extractor and exact-span
verifier the product uses (``extract_from_pages``), then compares the verified rows with the
page's gold rows. That measures what matters: facts that survive verification, not
character accuracy. Cost per page comes from the recorded run (or the provider's price
table, always marked unverified) so ``correct_rows_per_dollar`` and ``f1_per_dollar`` are
comparable across providers.

Nothing here is product behaviour. No application code imports this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from gridlens.ingestion.parsers.permit_docs import extract_from_pages

RowKey = tuple[str, str, str, str, int | None]  # type, drive, rating, unit, count
PRICE_NOTE = "unverified list price; confirm in the vendor console before relying on it"


@dataclass(frozen=True, slots=True)
class OcrReading:
    text: str
    cost_usd: Decimal


class OcrProvider(Protocol):
    name: str

    def read(self, page_id: str) -> OcrReading:
        """Return the provider's transcript and cost for one gold-set page."""
        ...


@dataclass(slots=True)
class RecordedProvider:
    """Replays a recorded transcript per page. No network, no key, no vendor SDK."""

    name: str
    transcripts: dict[str, str]
    cost_per_page_usd: Decimal
    price_note: str = PRICE_NOTE
    recorded_costs: dict[str, Decimal] = field(default_factory=dict)

    def read(self, page_id: str) -> OcrReading:
        if page_id not in self.transcripts:
            raise KeyError(f"{self.name} has no recorded transcript for {page_id}")
        cost = self.recorded_costs.get(page_id, self.cost_per_page_usd)
        return OcrReading(self.transcripts[page_id], cost)


# Default per-page prices used only when a recording carries no measured cost. All unverified.
DEFAULT_PAGE_PRICES: dict[str, Decimal] = {
    "openai-vision": Decimal("0.01"),
    "textract": Decimal("0.0015"),
    "mistral-ocr": Decimal("0.001"),
}


@dataclass(slots=True)
class ProviderScore:
    provider: str
    pages: int
    gold_rows: int
    predicted_rows: int
    true_positive: int
    precision: float
    recall: float
    f1: float
    total_cost_usd: Decimal
    correct_rows_per_dollar: float | None
    f1_per_dollar: float | None
    missing_pages: list[str] = field(default_factory=list)
    price_note: str = PRICE_NOTE


def _gold_keys(rows: list[dict[str, Any]]) -> list[RowKey]:
    return [
        (
            str(r["type"]),
            str(r.get("drive", "unknown")),
            str(Decimal(str(r["rating"]))),
            str(r["unit"]),
            r.get("count"),
        )
        for r in rows
    ]


def _predicted_keys(text: str, page_id: str) -> list[RowKey]:
    result = extract_from_pages([text], document_hash=f"bakeoff:{page_id}")
    rows = result.demand_rows + result.supply_rows
    return [(r.equipment_type, r.drive, str(r.rating), r.unit, r.count) for r in rows]


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def score_provider(provider: OcrProvider, gold_pages: list[dict[str, Any]]) -> ProviderScore:
    true_positive = predicted_total = gold_total = 0
    cost = Decimal("0")
    missing: list[str] = []
    for page in gold_pages:
        page_id = str(page["page_id"])
        gold = _gold_keys(page["gold_rows"])
        gold_total += len(gold)
        try:
            reading = provider.read(page_id)
        except KeyError:
            missing.append(page_id)
            continue
        cost += reading.cost_usd
        predicted = _predicted_keys(reading.text, page_id)
        predicted_total += len(predicted)
        remaining = list(gold)
        for key in predicted:
            if key in remaining:
                remaining.remove(key)  # a gold row can be matched once
                true_positive += 1
    precision = _ratio(true_positive, predicted_total)
    recall = _ratio(true_positive, gold_total)
    f1 = _ratio(2 * precision * recall, precision + recall)
    dollars = float(cost)
    return ProviderScore(
        provider=provider.name,
        pages=len(gold_pages) - len(missing),
        gold_rows=gold_total,
        predicted_rows=predicted_total,
        true_positive=true_positive,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        total_cost_usd=cost,
        correct_rows_per_dollar=round(true_positive / dollars, 2) if dollars > 0 else None,
        f1_per_dollar=round(f1 / dollars, 2) if dollars > 0 else None,
        missing_pages=missing,
        price_note=getattr(provider, "price_note", PRICE_NOTE),
    )


def load_recorded_providers(spec: dict[str, Any]) -> list[RecordedProvider]:
    """Build providers from a recording file: ``{"providers": {"name": {...}}}``."""
    providers: list[RecordedProvider] = []
    for name, body in sorted(spec["providers"].items()):
        providers.append(
            RecordedProvider(
                name=name,
                transcripts={str(k): str(v) for k, v in body["transcripts"].items()},
                cost_per_page_usd=Decimal(
                    str(body.get("cost_per_page_usd", DEFAULT_PAGE_PRICES.get(name, "0")))
                ),
                recorded_costs={
                    str(k): Decimal(str(v)) for k, v in body.get("recorded_costs_usd", {}).items()
                },
                price_note=str(body.get("price_note", PRICE_NOTE)),
            )
        )
    return providers


def run_bakeoff(gold_path: Path, recordings_path: Path) -> list[ProviderScore]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    recordings = json.loads(recordings_path.read_text(encoding="utf-8"))
    pages = gold["pages"]
    scores = [score_provider(p, pages) for p in load_recorded_providers(recordings)]
    return sorted(scores, key=lambda s: (-(s.f1_per_dollar or 0.0), s.provider))


def render_markdown(scores: list[ProviderScore]) -> str:
    lines = [
        "| Provider | Pages | Precision | Recall | F1 | Cost (USD) | Correct rows / $ | F1 / $ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in scores:
        lines.append(
            f"| {s.provider} | {s.pages} | {s.precision:.2f} | {s.recall:.2f} | {s.f1:.2f} "
            f"| {s.total_cost_usd:.4f} | {s.correct_rows_per_dollar or 'n/a'} "
            f"| {s.f1_per_dollar or 'n/a'} |"
        )
    lines.append("")
    lines.append(f"Prices are {PRICE_NOTE}. Gold pages are synthetic unless the file says so.")
    return "\n".join(lines)


def scores_as_json(scores: list[ProviderScore]) -> list[dict[str, Any]]:
    return [
        {
            **{k: v for k, v in s.__dict__.items() if k != "total_cost_usd"},
            "total_cost_usd": str(s.total_cost_usd),
        }
        for s in scores
    ]
