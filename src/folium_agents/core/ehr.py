"""Provider-neutral contracts for EHR-backed chat."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from folium_agents.core.financial import ClaimSearch

PATIENT_SEARCH_SESSION_TTL_SECONDS = 30 * 60


class AuthorizationExpired(ValueError):
    """The provider authorization is expired or unavailable."""


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
class PatientSearchCriteria:
    patient_id: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    birth_date: str | None = None


@dataclass(frozen=True)
class PatientSearchCandidate:
    patient_id: str
    given_name: str | None
    family_name: str | None
    birth_date: str | None


@dataclass(frozen=True)
class PatientSearchResult:
    candidates: list[PatientSearchCandidate]
    total: int | None
    more_matches_available: bool


class PatientSearchAuthorizationExpired(ValueError):
    pass


class PatientSearchDenied(ValueError):
    pass


class PatientSearchRejected(ValueError):
    pass


class PatientSearchFailed(ValueError):
    pass


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


@runtime_checkable
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


@runtime_checkable
class PatientSearchConnector(Protocol):
    """Provider capability for separately authorized patient discovery."""

    async def start_patient_search_authorization(
        self,
        session_id: str,
    ) -> AuthorizationRequest: ...

    async def complete_patient_search_authorization(
        self,
        session_id: str,
        *,
        state: str,
        code: str,
    ) -> None: ...

    async def search_patient_candidates(
        self,
        session_id: str,
        criteria: PatientSearchCriteria,
    ) -> PatientSearchResult: ...

    def end_patient_search_session(self, session_id: str) -> None: ...


@runtime_checkable
class PatientClaimsConnector(Protocol):
    """Optional capability for patient-bound financial evidence."""

    async def search_patient_claims(
        self,
        session_id: str,
        patient_id: str,
    ) -> ClaimSearch: ...


@dataclass(frozen=True)
class EHRProvider:
    """Validated provider instance and its explicitly available capabilities."""

    provider_id: str
    connector: EHRConnector | None
    patient_search: PatientSearchConnector | None
    claims: PatientClaimsConnector | None
