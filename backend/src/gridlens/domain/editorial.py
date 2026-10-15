"""Publication-safe projection of explicitly reviewed, retained public evidence.

Editorial approval is separate from commercial qualification. No pursuit, CRM,
contact, call-fact or research table is an input to this module.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Text = Annotated[str, Field(min_length=1, max_length=1200)]
Score = Annotated[int, Field(strict=True, ge=0, le=3)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Review(StrictModel):
    reviewer: Text
    reviewedAt: datetime
    classificationVerified: Literal[True]
    publicOnly: Literal[True]
    readerValue: Score
    specificity: Score
    significance: Score
    originality: Score
    technicalRelevance: Score


class EditorialReview(StrictModel):
    evidenceId: Text
    evidenceHash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    title: Text
    publicationEligibility: str
    geography: Text
    industry: Text
    eventClassification: Literal[
        "permitting",
        "project-milestone",
        "electricity-availability",
        "utility-infrastructure",
        "fuel-infrastructure",
        "equipment-schedule",
        "energy-market",
    ]
    whatChanged: Text
    verifiedFacts: Annotated[list[Text], Field(min_length=1, max_length=8)]
    unknowns: Annotated[list[Text], Field(min_length=1, max_length=12)]
    interpretations: Annotated[list[Text], Field(max_length=8)]
    hypotheses: Annotated[list[Text], Field(max_length=8)]
    commercialSignificance: Text
    technicalImplications: Text
    editorialAngles: Annotated[list[Text], Field(min_length=1, max_length=5)]
    whyNow: Text
    recommendedArticleType: Literal["research-brief", "deep-dive", "email-roundup", "educational"]
    evidenceQuality: Literal["primary", "reported"]
    confidence: Literal["low", "medium", "high"]
    review: Review


def canonical_url(value: str) -> str:
    p = urlsplit(value)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise ValueError("unsafe_source_url")
    if any(
        k.lower() in {"token", "access_token", "api_key", "apikey", "password", "signature"}
        for k, _ in parse_qsl(p.query)
    ):
        raise ValueError("unsafe_source_url")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        ("https", p.hostname.lower(), p.path.rstrip("/") or "/", urlencode(sorted(query)), "")
    )


def evaluate_feed(reviews, records, *, now=None, recent_ids=(), allowed_hosts=None):
    """records maps evidence IDs to (Observation, Evidence, Source); read only.

    A clearance applies to one exact evidence hash, never a whole project.
    Quotes remain attributed publisher claims, not independently proven truths.
    Dates of re-fetch/export never establish a material development.
    """
    now = now or datetime.now(UTC).date()
    items, rejected = [], []
    seen_ids, seen_urls = set(recent_ids), set()
    for index, raw in enumerate(reviews):
        identifier = str(index)
        try:
            try:
                review = EditorialReview.model_validate(raw)
            except ValidationError as exc:
                raise ValueError("invalid_review") from exc
            identifier = review.evidenceId
            if review.publicationEligibility != "approved-public":
                raise ValueError("publication_restricted")
            record = records.get(review.evidenceId)
            if not record:
                raise ValueError("missing_or_superseded_evidence")
            obs, evidence, source = record
            if evidence.content_hash != review.evidenceHash:
                raise ValueError("evidence_changed")
            source_url = canonical_url(evidence.url)
            host = urlsplit(source_url).hostname
            if allowed_hosts is not None and host not in allowed_hosts.get(source.id, set()):
                raise ValueError("source_not_authorized")
            if not evidence.published_at:
                raise ValueError("missing_publication_date")
            age = (now - evidence.published_at).days
            if age < 0 or age > 30:
                raise ValueError("future_date" if age < 0 else "stale")
            if review.review.reviewedAt.tzinfo is None or review.review.reviewedAt.date() > now:
                raise ValueError("invalid_review_date")
            if obs.first_seen_at.date() > now:
                raise ValueError("future_date")
            if not review.geography.startswith("United States"):
                raise ValueError("unrelated_market")
            retained = " ".join((evidence.title + " " + (evidence.abstract or "")).split())
            if " ".join(review.title.split()) not in retained:
                raise ValueError("unsupported_title")
            if any(" ".join(f.split()) not in retained for f in review.verifiedFacts):
                raise ValueError("unsupported_fact")
            if " ".join(review.whatChanged.split()) not in retained:
                raise ValueError("unsupported_change")
            event_id = "gridlens:" + str(obs.id)
            if event_id in seen_ids or source_url in seen_urls:
                raise ValueError("duplicate")
            judgment = review.review
            if min(judgment.readerValue, judgment.specificity, judgment.significance) < 2:
                raise ValueError("insufficient_editorial_value")
            score = (
                sum(
                    [
                        judgment.readerValue,
                        judgment.specificity,
                        judgment.significance,
                        judgment.originality,
                        judgment.technicalRelevance,
                    ]
                )
                + (3 if age <= 7 else 2 if age <= 14 else 1)
                + (3 if review.evidenceQuality == "primary" else 1)
            )
            if score < 14 or review.confidence == "low":
                raise ValueError("insufficient_editorial_value")
            seen_ids.add(event_id)
            seen_urls.add(source_url)
            item = review.model_dump(mode="json", exclude={"review", "evidenceId", "evidenceHash"})
            item.update(
                {
                    "id": event_id,
                    "origin": "gridlens",
                    "sourceUrl": source_url,
                    "publisher": source.publisher,
                    "sourceType": source.family,
                    "publishedAt": evidence.published_at.isoformat(),
                    "firstSeenAt": obs.first_seen_at.isoformat(),
                    "lastMaterialChangeAt": None,
                    "verifiedFacts": [
                        {
                            "text": fact,
                            "evidenceIds": [str(evidence.id)],
                            "status": "source-reported",
                        }
                        for fact in review.verifiedFacts
                    ],
                    "evidence": [
                        {
                            "id": str(evidence.id),
                            "url": source_url,
                            "contentHash": evidence.content_hash,
                            "publishedAt": evidence.published_at.isoformat(),
                        }
                    ],
                    "score": score,
                }
            )
            items.append(item)
        except ValueError as exc:
            rejected.append({"id": identifier, "reason": str(exc)})
    items.sort(key=lambda item: (-item["score"], item["publishedAt"], item["id"]))
    rejected.extend({"id": item["id"], "reason": "below_top_candidates"} for item in items[3:])
    return {
        "version": "2g-editorial/1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "items": items[:3],
        "rejected": rejected,
    }
