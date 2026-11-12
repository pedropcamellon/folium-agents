"""Provider-neutral contracts for EHR-backed chat."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthorizationRequest:
    state: str
    authorization_url: str


@dataclass(frozen=True)
class EHRConnectionStatus:
    connected: bool
    patient_id: str


@dataclass(frozen=True)
class PatientDemographics:
    patient_id: str
    given_name: str | None
    family_name: str | None
    birth_date: str | None


@dataclass(frozen=True)
class EvidenceRecord:
    source_type: str
    source_id: str
    title: str
    date: str | None
    status: str | None
    data: dict[str, object]


@dataclass(frozen=True)
class ChartEvidence:
    patient_id: str
    records: list[EvidenceRecord]
    warnings: list[str]
    complete: bool


class EHRConnector(Protocol):
    """Provider implementation for an explicitly selected patient."""

    name: str

    async def start_authorization(
        self,
        session_id: str,
        patient_id: str,
    ) -> AuthorizationRequest: ...

    async def complete_authorization(
        self,
        session_id: str,
        *,
        state: str,
        code: str,
    ) -> None: ...

    async def get_connection_status(
        self,
        session_id: str,
        patient_id: str,
    ) -> EHRConnectionStatus: ...

    async def get_patient_demographics(
        self,
        session_id: str,
        patient_id: str,
    ) -> PatientDemographics: ...

    async def retrieve_patient_chart(
        self,
        session_id: str,
        patient_id: str,
    ) -> ChartEvidence: ...

    def end_session(self, session_id: str) -> None: ...
