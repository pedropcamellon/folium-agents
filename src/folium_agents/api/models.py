"""FastAPI request, response, and session models."""

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderOperation = Literal["patient_search", "patient_chat", "claims"]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOLIUM_AGENTS_", extra="ignore")

    frontend_origin: str = "http://localhost:3000"
    patient_search_provider: str = "epic"
    enabled_providers: str = "epic"
    model_base_url: str = ""
    model_name: str = ""
    log_model_responses: bool = False
    require_model_citations: bool = True
    model_reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] = "low"
    model_api_key: str = ""
    model_api_key_header: Literal["api-key", "Authorization"] = "api-key"


class PatientSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(min_length=1, max_length=128, alias="patientId")
    provider_id: str = Field(default="epic", alias="providerId")


class CreatedSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    patient_id: str = Field(alias="patientId")
    authorization_url: str = Field(alias="authorizationUrl")


class CreatedPatientSearchSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    authorization_url: str = Field(alias="authorizationUrl")


class PatientSearchCriteria(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    given_name: str = Field(min_length=1, max_length=200, alias="givenName")
    family_name: str = Field(min_length=1, max_length=200, alias="familyName")
    birth_date: date = Field(alias="birthDate")

    @field_validator("given_name", "family_name")
    @classmethod
    def normalize_name_part(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_search_criteria(self) -> "PatientSearchCriteria":
        if not self.given_name or not self.family_name:
            raise ValueError("Provide a given name, family name, and date of birth.")
        return self


class PatientSearchCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(alias="patientId")
    given_name: str | None = Field(alias="givenName")
    family_name: str | None = Field(alias="familyName")
    birth_date: date | None = Field(alias="birthDate")


class PatientSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidates: list[PatientSearchCandidate]
    total: int | None = None
    more_matches_available: bool = Field(alias="moreMatchesAvailable")


class ChatTurn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ChatSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: str = Field(alias="sourceType")
    source_id: str = Field(alias="sourceId")
    title: str
    date: str | None = None
    status: str | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str
    sources: list[ChatSource]
    warnings: list[str]
    limitations: list[str] = Field(default_factory=list)
    session_id: str = Field(alias="sessionId")


class SourceCitation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: str = Field(alias="sourceType")
    source_id: str = Field(alias="sourceId")


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[SourceCitation] = Field(default_factory=list)


class ConnectionStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connected: bool
    patient_id: str = Field(alias="patientId")
    authorization_state: Literal["authorized", "authorization_required"] = Field(
        alias="authorizationState"
    )
    supported_operations: list[ProviderOperation] = Field(alias="supportedOperations")


class ProviderInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider_id: str = Field(alias="providerId")
    supported_operations: list[ProviderOperation] = Field(alias="supportedOperations")


class PatientProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(alias="patientId")
    given_name: str | None = Field(alias="givenName")
    family_name: str | None = Field(alias="familyName")
    birth_date: str | None = Field(alias="birthDate")


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["assistant", "user"]
    content: str


class SavedChatConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    provider_id: str
    authorization_state: Literal[""] = ""
    created_at: float


@dataclass
class ChatSessionState:
    patient_id: str
    provider_id: str
    authorization_state: str
    created_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class PatientSearchSessionState:
    provider_id: str
    authorization_state: str
    created_at: float = field(default_factory=time.time)
