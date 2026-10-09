"""Evidence-only pursuit contracts and published deterministic ordering policy."""

from datetime import date as Date
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    published_at: Date | None = None
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
    outcome: Literal[
        "Not reached",
        "Contacted",
        "Needs follow-up",
        "Reached buying organization",
        "Qualified",
        "No requirement",
        "Closed",
    ]
    next_action: str = Field(max_length=1000)
    follow_up: Date | None = None


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


class CommercialResearchBody(BaseModel):
    question: str = Field(min_length=12, max_length=300)


class ResearchRouteOut(BaseModel):
    query: str | None = None
    kind: str
    family: str
    status: str
    source_id: str | None = None
    external_id: str | None = None
    url: str | None = None
    reason: str | None = None


class ResearchContextOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    route_plan: list[ResearchRouteOut] = Field(default_factory=list)


class ResearchSourceCheckOut(BaseModel):
    event_date: Date | None = None
    match_basis: str | None = None
    evidence_url: str | None = None
    claim_type: str | None = None
    publisher: str | None = None
    extraction_location: str | None = None
    checked_at: datetime | None = None
    cache_reused: bool = False
    duplicate: bool = False
    url: str
    disposition: str
    reason: str
    evidence_id: str | None = None
    label: str | None = None
    excerpt: str | None = None
    published_at: Date | None = None
    retrieved_at: datetime | None = None


class ResearchReceiptOut(BaseModel):
    route_results: list[ResearchRouteOut] = Field(default_factory=list)
    source_checks: list[ResearchSourceCheckOut] = Field(default_factory=list)
    resulting_evidence_ids: list[str] = Field(default_factory=list)
    queries_generated: list[str] = Field(default_factory=list)
    queries_attempted: list[str] = Field(default_factory=list)
    queries_searched: list[str] = Field(default_factory=list)
    acquisition_limitations: list[str] = Field(default_factory=list)
    reevaluation_status: str = "NOT_STARTED"
    next_action: str | None = None
    before: str | None = None
    after: str | None = None
    reason: str | None = None
    error: str | None = None
    tier: str | None = None
    remaining_blockers: list[str] = Field(default_factory=list)
    runtime_seconds: float | None = None
    searches: int = 0
    retrieval_attempts: int = 0
    model_calls: int = 0
    cost_usd: str | None = None
    reserved_cost_usd: str | None = None


class ResearchQuestionOut(BaseModel):
    id: UUID
    project_id: UUID
    need_id: UUID
    pursuit_id: UUID
    category: str
    question: str
    status: str
    attempt_count: int
    created_at: datetime
    completed_at: datetime | None
    retry_after: datetime | None
    query_fingerprint: str
    evidence_fingerprint: str
    context: ResearchContextOut
    budget: dict
    receipt: ResearchReceiptOut


class AutonomousResearchOut(BaseModel):
    items: list[ResearchQuestionOut]


class AutonomousResearchBody(BaseModel):
    force: bool = False


class CommercialTriageFact(BaseModel):
    text: str | None
    evidence_id: str | None
    url: str | None
    hash: str | None
    date: str | None


class CommercialTriageContact(BaseModel):
    organization: str | None
    person: str | None
    role: str | None
    kind: str | None
    value: str | None
    source_url: str | None
    evidence_ids: list[str] = Field(default_factory=list)


class CommercialTriageStage(BaseModel):
    stage: str
    date: str | None
    source_url: str | None
    evidence_id: str | None


class CommercialTriageLifecycleEvent(BaseModel):
    state: str
    event_type: str
    date: str | None
    value_kind: str
    evidence_url: str
    current: bool = True
    published_at: Date | None = None
    event_date_label: str | None = None


class CommercialTriageNeedState(BaseModel):
    need_id: UUID
    project_id: UUID
    disposition: str
    reason: str
    held: bool = False
    conflict_state: str | None = None
    closed: bool = False


class CommercialTriageOperatorFactRef(BaseModel):
    """Compact as-of pointer to an accepted exact-need operator fact."""

    need_id: UUID
    fact_version_id: UUID
    content_hash: str
    authority: Literal["User-confirmed"] = "User-confirmed"


class CommercialTriageCard(BaseModel):
    research_state: dict = Field(default_factory=dict)
    id: UUID
    project_id: UUID
    related_project_ids: list[UUID] = Field(default_factory=list)
    pursuit_id: UUID | None = None
    name: str
    location: str | None
    tier: str
    activity: str
    industry: str
    related_need_ids: list[UUID] = Field(default_factory=list)
    related_need_states: list[CommercialTriageNeedState] = Field(default_factory=list)
    disposition: str
    reason: str
    required_mw: str | None
    start_window: str | None
    duration: str | None
    supply: str
    stage: CommercialTriageStage
    lifecycle_timeline: list[CommercialTriageLifecycleEvent] = Field(default_factory=list)
    organization: str | None
    organization_role: str | None
    contacts: list[CommercialTriageContact] = Field(default_factory=list)
    facts: list[CommercialTriageFact] = Field(default_factory=list)
    hypothesis: str | None
    unknowns: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_question: str
    next_action: str
    watch: dict | None = None
    sources: list[CommercialTriageFact] = Field(default_factory=list)
    operator_fact_refs: list[CommercialTriageOperatorFactRef] | None = None
    conflict_state: str | None
    input_hash: str
    notes: list[CallNoteOut] = Field(default_factory=list)


class CommercialTriageCounts(BaseModel):
    action_now: int
    research: int
    watch: int
    reject: int


class CommercialTriageDaily(BaseModel):
    evaluated: int
    surfaced: int
    contacted: int
    reached_buyer: int | None = None
    qualified: int | None = None
    promoted_prospects: int | None = None
    promoted_leads: int | None = None
    supported_mw: str | None = None
    metric_scope: list[str] = Field(default_factory=list)
    unavailable_metrics: list[str] = Field(default_factory=list)


class ResearchMetricsOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    blockers_attempted: int = 0
    blocker_statuses: dict[str, int] = Field(default_factory=dict)
    commercial_transitions: dict[str, int] = Field(default_factory=dict)
    evidence_tier_transitions: dict[str, int] = Field(default_factory=dict)


class ResearchChangeOut(BaseModel):
    id: str
    pursuit_id: UUID
    need_id: UUID
    project_id: UUID
    version: int
    evaluated_at: datetime | None = None
    name: str
    before: str
    after: str
    before_tier: str | None = None
    after_tier: str | None = None
    reason: str | None = None
    next_action: str | None = None
    new_evidence: list[CommercialTriageFact] = Field(default_factory=list)
    question_ids: list[UUID] = Field(default_factory=list)


class ResearchOverviewOut(BaseModel):
    since: datetime | None = None
    summary: ResearchMetricsOut
    items: list[ResearchChangeOut] = Field(default_factory=list)


class CommercialTriageOut(BaseModel):
    research_overview: ResearchOverviewOut | None = None
    evaluated_at: datetime
    policy_version: str
    total: int
    cohort_counts: CommercialTriageCounts
    daily: CommercialTriageDaily
    items: list[CommercialTriageCard]


class CommercialTriageHistoryVersion(BaseModel):
    version: int
    disposition: str
    evaluated_at: datetime | None = None
    evaluated_on: Date | None = None
    input_hash: str | None = None
    operator_fact_provenance: Literal["recorded", "legacy_unknown"] = "legacy_unknown"
    snapshot_status: Literal["saved_as_of", "metadata_only"]
    live_status: Literal["not_rechecked"] = "not_rechecked"
    saved_card: CommercialTriageCard | None = None


class CommercialTriageHistoryItem(BaseModel):
    pursuit_id: UUID
    need_id: UUID
    project_id: UUID
    related_project_ids: list[UUID] = Field(default_factory=list)
    disposition: str
    evaluated_at: datetime | None = None
    evaluated_on: Date | None = None
    input_hash: str | None = None
    snapshot_status: Literal["saved_as_of", "metadata_only"]
    live_status: Literal["not_rechecked"] = "not_rechecked"
    saved_card: CommercialTriageCard | None = None
    notes: list[CallNoteOut] = Field(default_factory=list)
    versions: list[CommercialTriageHistoryVersion] = Field(default_factory=list)


class CommercialResearchStatusOut(BaseModel):
    status: Literal["pending", "ready", "failed", "superseded", "not_requested"]
    job_id: UUID | None = None
    input_hash: str
    generated_at: datetime | None = None
    result: dict | None = None
    citations: list[dict] = Field(default_factory=list)
    error: str | None = None


class CommercialTriageHistoryOut(BaseModel):
    items: list[CommercialTriageHistoryItem]
