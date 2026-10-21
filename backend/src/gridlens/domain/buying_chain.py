"""Small, evidence-only buying-chain contracts and conservative relationship policy."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

POLICY_VERSION = "buying-chain-v2-permits"
MAX_CANDIDATES = 8
MAX_DOCUMENTS = 8
MAX_SOURCE_URLS = 4
ROLE_MAX_AGE_DAYS = 365


class Category(StrEnum):
    ELECTRICAL = "electrical_contractor"
    GC = "general_contractor"
    EPC = "epc"
    COMMISSIONING = "commissioning"
    OWNER_CONSTRUCTION = "owner_construction"
    OWNER_ENERGY = "owner_energy"
    OWNER = "owner_developer"
    OPERATOR = "asset_operator"
    FIELD_OPERATIONS = "field_operations"
    PROCUREMENT = "procurement"
    UNKNOWN = "unknown"


CATEGORY_PRIORITY = {category.value: position for position, category in enumerate(Category)}


class BuyingEvidenceOut(BaseModel):
    id: UUID
    url: str
    quote: str
    supports: str
    extraction_location: str
    published_at: date | None
    observed_at: datetime
    content_hash: str


class PublicContactOut(BaseModel):
    kind: str
    value: str
    source_url: str
    quote: str
    observed_at: datetime


class BuyingCandidateOut(BaseModel):
    id: UUID
    organization: str
    person_name: str | None
    title: str | None
    category: str
    organization_relationship: str
    person_organization_relationship: str
    person_project_relationship: str
    evidence_strength: str
    reason: str
    observed_at: datetime
    verified_at: datetime | None
    public_contacts: list[PublicContactOut] = Field(default_factory=list)
    evidence: list[BuyingEvidenceOut] = Field(default_factory=list)
    history_count: int = 1
    stale: bool = False
    fingerprint: str | None = None
    correction_version: str | None = None
    correction_history: list[dict] = Field(default_factory=list)
    correction_stale: bool = False
    retracted: bool = False
    reported_contacts: list[dict] = Field(default_factory=list)


class BuyingRunOut(BaseModel):
    id: UUID
    status: str
    documents_checked: int
    candidates_added: int
    unresolved: list[str]
    created_at: datetime


class PermitFactOut(BaseModel):
    label: str
    value: str
    quote: str
    role_quote: str | None = None


class PermitSummaryOut(BaseModel):
    evidence_id: UUID
    source_id: str
    url: str
    title: str
    observed_at: datetime
    extraction_location: str
    facts: list[PermitFactOut] = Field(default_factory=list)


class BuyingChainResearchJobOut(BaseModel):
    id: UUID
    status: str
    detail_status: str | None = None
    created_at: datetime


class BuyingChainOut(BaseModel):
    project_id: UUID
    status: str
    candidates: list[BuyingCandidateOut] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    runs: list[BuyingRunOut] = Field(default_factory=list)
    permit_summaries: list[PermitSummaryOut] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION
    research_job: BuyingChainResearchJobOut | None = None


class BuyingEnrichBody(BaseModel):
    source_urls: list[str] = Field(default_factory=list, max_length=MAX_SOURCE_URLS)


class BuyingChainCorrectionBody(BaseModel):
    expected_version: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=120)
    action: str = Field(pattern="^(correct|retract)$")
    values: dict[str, str | None] = Field(default_factory=dict)
    source_evidence_id: UUID | None = None
    source_hash: str | None = Field(default=None, min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=1000)
    reported_contact: bool = False
    identity_type: str | None = Field(default=None, pattern="^(company|person)$")
    identity_id: UUID | None = None


class BuyingChainCorrectionOut(BaseModel):
    id: UUID
    claim_id: UUID
    project_id: UUID
    version: str
    action: str
    values: dict[str, str | None]
    reason: str
    actor: str
    created_at: datetime
    reported_contact: bool = False


def person_project_relationship(
    *,
    organization_direct: bool,
    current_role: bool,
    relevant_role: bool,
    direct_assignment: bool,
    ambiguous: bool = False,
) -> str:
    # Employment alone, an old title, or a model judgement cannot prove assignment.
    if ambiguous or not current_role or not organization_direct:
        return "UNKNOWN"
    if direct_assignment:
        return "DIRECT"
    if relevant_role:
        return "ROLE_SUPPORTED"
    return "UNKNOWN"


def current_role(published_at: date | None, today: date) -> bool:
    return published_at is not None and 0 <= (today - published_at).days <= ROLE_MAX_AGE_DAYS
