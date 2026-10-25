"""Public, generated API contracts for the canonical company graph."""

from __future__ import annotations

from pydantic import BaseModel


class GraphEvidence(BaseModel):
    id: str
    title: str | None
    url: str | None
    content_hash: str
    source_id: str | None
    observed_at: str | None
    published_at: str | None = None


class GraphIdentifier(BaseModel):
    identifier_type: str
    value: str
    evidence: GraphEvidence


class GraphCompany(BaseModel):
    id: str
    display_name: str | None
    identifiers: list[GraphIdentifier]
    aliases: list[GraphIdentifier]


class GraphProjectRole(BaseModel):
    role: str
    organization_name: str | None
    state: str
    evidence: GraphEvidence


class GraphProject(BaseModel):
    id: str
    name: str
    location: str | None
    roles: list[GraphProjectRole]


class GraphRelationship(BaseModel):
    id: str
    source_company_id: str
    target_company_id: str
    relationship_type: str
    status: str
    version: int
    correction_id: str | None = None
    reason: str | None
    evidence: GraphEvidence


class CompanyGraphOut(BaseModel):
    company: GraphCompany
    projects: list[GraphProject]
    relationships: list[GraphRelationship]
    evidence: list[GraphEvidence]
    limits: dict[str, int]
