from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Evidence(BaseModel):
    page_number: int = Field(ge=1)
    exact_text: str = Field(min_length=1)
    bbox: dict | None = None


class ContractParty(BaseModel):
    name: str
    role: str | None = None
    evidence: Evidence | None = None


class ContractTerm(BaseModel):
    name: str
    value: str | None
    evidence: Evidence | None = None
    confidence: float = Field(ge=0, le=1)


class ContractRisk(BaseModel):
    title: str
    severity: RiskSeverity
    clause_type: str
    explanation: str
    recommendation: str
    evidence: Evidence
    confidence: float = Field(ge=0, le=1)


class ContractReview(BaseModel):
    contract_id: str
    contract_type: str
    parties: list[ContractParty] = Field(default_factory=list)
    key_terms: list[ContractTerm] = Field(default_factory=list)
    risks: list[ContractRisk] = Field(default_factory=list)
    recommended_next_action: str
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_risk_evidence(self) -> "ContractReview":
        for risk in self.risks:
            if not risk.evidence.exact_text.strip():
                raise ValueError(f"Risk {risk.title!r} is missing evidence text")
        return self
