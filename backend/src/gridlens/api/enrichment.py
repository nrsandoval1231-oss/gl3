"""Authenticated enrichment reads; source imports remain an isolated operator task."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gridlens.domain.company_graph import CompanyGraphOut
from gridlens.domain.power_enrichment import PowerEnrichment
from gridlens.persistence.database import SessionLocal
from gridlens.security import require_same_origin, require_session

router = APIRouter(prefix="/api", tags=["enrichment"], dependencies=[Depends(require_session)])


class ContactCorrectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    expected_version: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=120)
    action: Literal["suppress", "replace", "retract"]
    kind: Literal["email", "phone", "profile", "website", "general"] = "email"
    value: str | None = Field(default=None, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    source_evidence_id: UUID | None = None
    source_hash: str | None = Field(default=None, min_length=64, max_length=64)


@router.get("/companies/{company_id}/graph", response_model=CompanyGraphOut)
def company_graph(company_id: UUID):
    from gridlens.intelligence.company_graph import company_graph as read_graph

    with SessionLocal() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        try:
            return read_graph(session, company_id)
        except LookupError as exc:
            raise HTTPException(404, "Company not found") from exc


@router.get("/companies/{company_id}/contact-assertions", response_model=dict[str, Any])
def contact_assertions(company_id: UUID):
    from gridlens.intelligence.contact_assertions import project_contact_assertions
    from gridlens.persistence.models import CompanyIdentity

    with SessionLocal() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if session.get(CompanyIdentity, company_id) is None:
            raise HTTPException(404, "Company not found")
        return project_contact_assertions(session, company_id)


@router.post(
    "/contact-assertions/{claim_id}/corrections",
    response_model=dict[str, Any],
    dependencies=[Depends(require_same_origin)],
)
def correct_contact(claim_id: UUID, body: ContactCorrectionBody):
    from gridlens.intelligence.contact_assertions import correct_contact_assertion

    with SessionLocal.begin() as session:
        try:
            return correct_contact_assertion(
                session, claim_id=claim_id, actor="authenticated-operator", **body.model_dump()
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc


@router.get("/projects/{project_id}/power-enrichment", response_model=PowerEnrichment)
def project_power_enrichment(project_id: UUID):
    from gridlens.intelligence.project_enrichment import project_power_enrichment as project_power

    with SessionLocal() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        result = project_power(session, project_id)
        if result is None:
            raise HTTPException(404, "Eligible project not found")
        return result
