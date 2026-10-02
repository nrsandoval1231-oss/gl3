"""Evidence-only pursuit contracts and published deterministic ordering policy."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

POLICY_VERSION = "power-pursuits-v1"
SOURCES = (
    "austin-building-permits",
    "texas-rrc-drilling-permits",
    "houston-weekly-permits",
    "dallas-monthly-permits",
    "el-paso-new-commercial-permits",
    "boston-building-permits",
)
MAX_BATCH = 12
MAX_FETCHES = 48
MAX_MODELS = 4
ActionStatus = Literal["Call now", "Verify first", "Monitor", "Drop"]


class PursuitSourceOut(BaseModel):
    url: str
    title: str
    excerpt: str
    retrieved_at: datetime
    published_at: date | None = None
    source_date: str = "Publication date unknown"
    match_reason: str
    content_hash: str


class PursuitPersonOut(BaseModel):
    name: str
    organization: str
    corporate_role: str
    project_assignment: str
    purchasing_authority: str = "Unknown"
    source_url: str


class PursuitContactOut(BaseModel):
    organization: str
    kind: str
    value: str
    source_url: str
    label: str


class CallNoteBody(BaseModel):
    client_id: UUID
    note: str = Field(max_length=5000)
    outcome: Literal["Not reached", "Contacted", "Needs follow-up", "No requirement", "Closed"]
    next_action: str = Field(max_length=1000)
    follow_up: date | None = None


class CallNoteOut(CallNoteBody):
    id: UUID
    owner: str
    created_at: datetime


class PursuitOut(BaseModel):
    id: UUID
    project_id: UUID
    project_ids: list[UUID]
    project: str
    site: str
    organization: str
    organization_involvement: str
    action_status: ActionStatus
    rank_key: list[int]
    ranking_reasons: list[str]
    trigger: str
    trigger_date: str
    timing: list[str]
    registration_context: list[str] = Field(default_factory=list)
    people: list[PursuitPersonOut]
    contacts: list[PursuitContactOut]
    load_facts: list[str]
    fuel_facts: list[str]
    utility_facts: list[str]
    unknowns: list[str]
    conflicts: list[str]
    next_action: str
    evidence: list[PursuitSourceOut]
    last_researched_at: datetime | None
    last_attempt_at: datetime | None
    research_status: str
    research_errors: list[str]
    notes: list[CallNoteOut]
    tier: str = "Signal"


class PursuitJobOut(BaseModel):
    id: UUID
    status: str
    attempts: int
    error: str | None
    created_at: datetime
    checkpoint: str | None


class PursuitsOut(BaseModel):
    items: list[PursuitOut]
    usage: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    offset: int = 0
    excluded_count: int
    jobs: list[PursuitJobOut]
    policy_version: str = POLICY_VERSION
    ranking_policy: str = (
        "Lexicographic: explicit construction/commissioning power scope, then dated work "
        "timing, reachable project organization, then verified NG/propane feasibility. "
        "Stable identity breaks ties. No probability or tier promotion."
    )
    scheduler: str = (
        "Research is queued after successful Austin, RRC, Dallas, El Paso, or Houston ingestion. "
        "City permit refresh rechecks the official bounded source and exact retained row; "
        "A running worker is required; managed cloud scheduling has not been verified."
    )
