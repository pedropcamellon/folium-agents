"""Epic implementation of the provider-neutral EHR chat contract."""

import asyncio
import secrets
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict

from folium_agents.core.connections import connection_store
from folium_agents.core.diagnostics import diagnostic
from folium_agents.core.ehr import (
    PATIENT_SEARCH_SESSION_TTL_SECONDS,
    AuthorizationExpired,
    AuthorizationRequest,
    ChartEvidence,
    EHRConnectionStatus,
    EvidenceRecord,
    PatientDemographics,
    PatientSearchAuthorizationExpired,
    PatientSearchCandidate,
    PatientSearchCriteria,
    PatientSearchDenied,
    PatientSearchFailed,
    PatientSearchRejected,
    PatientSearchResult,
)
from folium_agents.core.financial import (
    ClaimAuthorizationExpired,
    ClaimSearch,
    ClaimSearchError,
)
from folium_agents.epic.epic import (
    DEFAULT_EPIC_SCOPE,
    MEDICATION_REVIEW_SCOPE,
    EpicConfig,
    EpicPatientSearchNoResults,
    EpicPatientSearchRejected,
    EpicSmartClient,
)
from folium_agents.epic.financial_reads import (
    FinancialReadError,
    search_claims,
    validate_claim_search_scope,
)
from folium_agents.epic.models import (
    EpicPatientSearchResult,
    EpicToken,
    SmartConfiguration,
)


class EpicReauthorizationRequired(AuthorizationExpired, ClaimAuthorizationExpired):
    pass


class SavedEpicConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    smart: SmartConfiguration
    token: EpicToken
    expires_at: float
    connection_expires_at: float
    binding: str


@dataclass
class EpicSession:
    patient_id: str
    smart: SmartConfiguration
    state: str
    verifier: str
    token: EpicToken | None = None
    expires_at: float | None = None
    connection_expires_at: float = 0


@dataclass
class EpicPatientSearchSession:
    smart: SmartConfiguration
    state: str
    verifier: str
    token: EpicToken | None = None
    expires_at: float | None = None
    connection_expires_at: float = 0


class EpicConnector:
    name = "epic"

    def __init__(self) -> None:
        self._sessions: dict[str, EpicSession] = {}
        self._patient_search_sessions: dict[str, EpicPatientSearchSession] = {}
        self._store = connection_store()
        self._refresh_lock = asyncio.Lock()

    def _binding(self) -> str:
        config = self._config()
        return (
            f"{config.issuer}|{config.client_id}|{config.redirect_uri}|{config.scope}"
        )

    def _save(self, session_id: str, session: EpicSession) -> None:
        if self._store and session.token:
            self._store.save(
                "epic",
                session_id,
                {
                    "patient_id": session.patient_id,
                    "smart": session.smart.model_dump(),
                    "token": session.token.model_dump(),
                    "expires_at": session.expires_at,
                    "connection_expires_at": session.connection_expires_at,
                    "binding": self._binding(),
                },
                session.connection_expires_at,
            )

    async def start_authorization(
        self,
        session_id: str,
        patient_id: str,
    ) -> AuthorizationRequest:
        config = self._config()
        client = EpicSmartClient(config)
        smart = await client.discover()
        state = client.create_state()
        verifier, challenge = client.create_pkce_pair()
        authorization_url = client.build_authorization_url(
            smart,
            state=state,
            code_challenge=challenge,
        )
        self._sessions[session_id] = EpicSession(
            patient_id=patient_id,
            smart=smart,
            state=state,
            verifier=verifier,
            connection_expires_at=time.time() + 24 * 60 * 60,
        )
        return AuthorizationRequest(state=state, authorization_url=authorization_url)

    async def start_patient_search_authorization(
        self,
        session_id: str,
    ) -> AuthorizationRequest:
        config = self._patient_search_config()
        client = EpicSmartClient(config)
        smart = await client.discover()
        state = client.create_state()
        verifier, challenge = client.create_pkce_pair()
        authorization_url = client.build_authorization_url(
            smart,
            state=state,
            code_challenge=challenge,
        )
        self._patient_search_sessions[session_id] = EpicPatientSearchSession(
            smart=smart,
            state=state,
            verifier=verifier,
            connection_expires_at=time.time() + PATIENT_SEARCH_SESSION_TTL_SECONDS,
        )
        return AuthorizationRequest(state=state, authorization_url=authorization_url)

    async def complete_patient_search_authorization(
        self,
        session_id: str,
        *,
        state: str,
        code: str,
    ) -> None:
        session = self._patient_search_session(session_id)
        if not secrets.compare_digest(session.state, state):
            raise ValueError("OAuth state mismatch; refusing token exchange.")
        token = await EpicSmartClient(self._patient_search_config()).exchange_code(
            session.smart,
            code=code,
            returned_state=state,
            expected_state=session.state,
            code_verifier=session.verifier,
        )
        session.expires_at = time.time() + self._validate_search_token(token)
        session.token = token
        session.verifier = ""
        session.state = ""

    async def search_patient_candidates(
        self,
        session_id: str,
        criteria: PatientSearchCriteria,
    ) -> PatientSearchResult:
        session = self._patient_search_session(session_id)
        try:
            token = await self._patient_search_access_token(session)
        except EpicReauthorizationRequired as error:
            raise PatientSearchAuthorizationExpired(str(error)) from error
        try:
            self._validate_patient_search_scope(token.scope)
        except EpicReauthorizationRequired as error:
            raise PatientSearchAuthorizationExpired(str(error)) from error
        try:
            result = await EpicSmartClient(
                self._patient_search_config()
            ).search_patients(
                token.access_token,
                patient_id=criteria.patient_id,
                given_name=criteria.given_name,
                family_name=criteria.family_name,
                birthdate=criteria.birth_date,
            )
        except EpicPatientSearchNoResults as error:
            diagnostic("fhir.patient_search_no_results", error=error)
            result = EpicPatientSearchResult(total=0, patients=[])
        except EpicPatientSearchRejected as error:
            raise PatientSearchRejected(
                "The provider rejected the patient search. Check its search "
                "requirements and Patient.Search access."
            ) from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 401:
                session.token = None
                session.expires_at = None
                raise PatientSearchAuthorizationExpired(
                    "Patient-search authorization expired. Connect again."
                ) from error
            if error.response.status_code == 403:
                raise PatientSearchDenied(
                    "The provider did not authorize patient search."
                ) from error
            if error.response.status_code == 400:
                raise PatientSearchRejected(
                    "The provider rejected the patient search. Check its search "
                    "requirements and Patient.Search access."
                ) from error
            raise PatientSearchFailed(
                "The provider could not complete the patient search."
            ) from error
        except (httpx.HTTPError, TimeoutError) as error:
            raise PatientSearchFailed(
                "The provider could not complete the patient search."
            ) from error
        return patient_search_result(result)

    def end_patient_search_session(self, session_id: str) -> None:
        self._patient_search_sessions.pop(session_id, None)

    async def complete_authorization(
        self,
        session_id: str,
        *,
        state: str,
        code: str,
    ) -> None:
        session = self._session(session_id)
        if not secrets.compare_digest(session.state, state):
            raise ValueError("OAuth state mismatch; refusing token exchange.")
        token = await EpicSmartClient(self._config()).exchange_code(
            session.smart,
            code=code,
            returned_state=state,
            expected_state=session.state,
            code_verifier=session.verifier,
        )
        lifetime = self._validate_token(token, session.patient_id)
        session.token = token
        session.expires_at = time.time() + lifetime
        session.verifier = ""
        session.state = ""
        self._save(session_id, session)

    async def get_connection_status(
        self,
        session_id: str,
        patient_id: str,
    ) -> EHRConnectionStatus:
        session = self._session(session_id)
        self._validate_patient(session, patient_id)
        if session.token is not None:
            try:
                await self._access_token(session)
            except ValueError:
                return EHRConnectionStatus(
                    connected=False, patient_id=session.patient_id
                )
        return EHRConnectionStatus(
            connected=session.token is not None,
            patient_id=session.patient_id,
        )

    async def get_patient_demographics(
        self,
        session_id: str,
        patient_id: str,
    ) -> PatientDemographics:
        session = self._session(session_id)
        self._validate_patient(session, patient_id)
        token = await self._access_token(session)
        try:
            patient = await EpicSmartClient(self._config()).get_patient(
                token.access_token,
                patient_id=session.patient_id,
            )
        except httpx.HTTPStatusError as error:
            self._handle_fhir_rejection(session, error)
            raise
        name = patient.primary_name
        return PatientDemographics(
            patient_id=patient.id,
            given_name=name.given[0] if name and name.given else None,
            family_name=name.family if name and name.family else None,
            birth_date=patient.birth_date,
        )

    async def retrieve_patient_chart(
        self,
        session_id: str,
        patient_id: str,
    ) -> ChartEvidence:
        session = self._session(session_id)
        self._validate_patient(session, patient_id)
        token = await self._access_token(session)
        try:
            review = await EpicSmartClient(self._config()).review_medications(
                token.access_token,
                patient_id=session.patient_id,
            )
        except httpx.HTTPStatusError as error:
            self._handle_fhir_rejection(session, error)
            raise
        records = [
            EvidenceRecord(
                source_type="MedicationRequest",
                source_id=item.resource_id,
                title=item.display,
                date=item.authored_on,
                status=item.status,
                data=item.model_dump(),
            )
            for item in review.active_medications
        ]
        records.extend(
            EvidenceRecord(
                source_type=resource_type,
                source_id=item.resource_id,
                title=item.display,
                date=item.date,
                status=item.clinical_status,
                data=item.model_dump(),
            )
            for resource_type, items in (
                ("AllergyIntolerance", review.allergies),
                ("Condition", review.conditions),
            )
            for item in items
        )
        return ChartEvidence(
            patient_id=session.patient_id,
            records=records,
            warnings=review.outcome_notes,
            complete=not any(
                " outcome warning/" in note for note in review.outcome_notes
            ),
        )

    async def search_patient_claims(
        self,
        session_id: str,
        patient_id: str,
    ) -> ClaimSearch:
        session = self._session(session_id)
        self._validate_patient(session, patient_id)
        token = await self._access_token(session)
        try:
            validate_claim_search_scope(token.scope)
        except FinancialReadError as error:
            raise ClaimSearchError(str(error)) from error
        async with httpx.AsyncClient() as client:
            try:
                return await search_claims(
                    issuer=self._config().issuer,
                    access_token=token.access_token,
                    patient_id=patient_id,
                    client=client,
                )
            except FinancialReadError as error:
                raise ClaimSearchError(str(error)) from error

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self._store:
            self._store.delete("epic", session_id)

    async def _access_token(self, session: EpicSession) -> EpicToken:
        async with self._refresh_lock:
            return await self._refresh_token(session)

    async def _patient_search_access_token(
        self,
        session: EpicPatientSearchSession,
    ) -> EpicToken:
        async with self._refresh_lock:
            token = session.token
            if (
                token is not None
                and session.expires_at is not None
                and session.expires_at > time.time() + 30
            ):
                return token
            if token is None or not token.refresh_token:
                session.token = None
                session.expires_at = None
                raise EpicReauthorizationRequired(
                    "Epic patient search authorization expired. Reconnect to search."
                )
            try:
                refreshed = await EpicSmartClient(
                    self._patient_search_config()
                ).refresh_access_token(session.smart, token.refresh_token)
            except httpx.HTTPStatusError as error:
                if error.response.status_code in {400, 401}:
                    session.token = None
                    session.expires_at = None
                    raise EpicReauthorizationRequired(
                        "Epic patient search authorization expired. Reconnect to search."
                    ) from error
                raise
            if refreshed.scope is None:
                refreshed.scope = token.scope
            if refreshed.refresh_token is None:
                refreshed.refresh_token = token.refresh_token
            session.expires_at = time.time() + self._validate_search_token(refreshed)
            session.token = refreshed
            return refreshed

    def _patient_search_session(
        self,
        session_id: str,
    ) -> EpicPatientSearchSession:
        session = self._patient_search_sessions.get(session_id)
        if session is None:
            raise EpicReauthorizationRequired(
                "Epic patient search authorization is unavailable. Reconnect to search."
            )
        if session.connection_expires_at <= time.time():
            self.end_patient_search_session(session_id)
            raise EpicReauthorizationRequired(
                "Epic patient search authorization expired. Reconnect to search."
            )
        return session

    @staticmethod
    def _validate_search_token(token: EpicToken) -> int:
        if token.patient is not None:
            raise EpicReauthorizationRequired(
                "Epic patient search requires a provider-context authorization."
            )
        if token.expires_in is None or token.expires_in <= 0:
            raise EpicReauthorizationRequired(
                "Epic patient search authorization is invalid. Reconnect to search."
            )
        EpicConnector._validate_patient_search_scope(token.scope)
        return token.expires_in

    @staticmethod
    def _validate_patient_search_scope(scope: str | None) -> None:
        if scope is None:
            return
        granted = set(scope.split())
        has_read = bool(
            {"user/Patient.rs", "user/Patient.read", "user/Patient.r"} & granted
        )
        has_search = bool(
            {"user/Patient.rs", "user/Patient.read", "user/Patient.s"} & granted
        )
        if not has_read or not has_search:
            raise EpicReauthorizationRequired(
                "Epic authorization is missing Patient read and search permissions."
            )

    async def _refresh_token(self, session: EpicSession) -> EpicToken:
        if (
            session.token is not None
            and session.expires_at is not None
            and session.expires_at > time.time() + 30
        ):
            return session.token
        previous = session.token
        refresh_token = previous.refresh_token if previous is not None else None
        if previous is None or not refresh_token:
            session.token = None
            self._discard_token(session)
            diagnostic("oauth.reauthorization_required")
            raise EpicReauthorizationRequired(
                "Epic patient authorization expired. Reauthorize this patient."
            )
        diagnostic("oauth.refresh_started")
        try:
            token = await EpicSmartClient(self._config()).refresh_access_token(
                session.smart,
                refresh_token,
            )
        except httpx.HTTPStatusError as error:
            diagnostic("oauth.refresh_failed", error=error)
            if error.response.status_code in {400, 401}:
                session.token = None
                self._discard_token(session)
                raise EpicReauthorizationRequired(
                    "Epic refresh authorization was rejected. Reauthorize this patient."
                ) from error
            raise
        if token.patient is None:
            token.patient = previous.patient
        if token.refresh_token is None:
            token.refresh_token = previous.refresh_token
        if token.scope is None:
            token.scope = previous.scope
        try:
            lifetime = self._validate_token(token, session.patient_id)
        except ValueError:
            session.token = None
            self._discard_token(session)
            raise
        session.token = token
        session.expires_at = time.time() + lifetime
        diagnostic("oauth.refresh_completed")
        for session_id, candidate in self._sessions.items():
            if candidate is session:
                self._save(session_id, session)
        return token

    def _discard_token(self, session: EpicSession) -> None:
        for session_id, candidate in self._sessions.items():
            if candidate is session and self._store:
                self._store.delete("epic", session_id)

    def _handle_fhir_rejection(
        self,
        session: EpicSession,
        error: httpx.HTTPStatusError,
    ) -> None:
        diagnostic("fhir.request_failed", error=error)
        if error.response.status_code == 401:
            session.token = None
            self._discard_token(session)

    def _session(self, session_id: str) -> EpicSession:
        if session_id not in self._sessions and self._store:
            payload = self._store.load("epic", session_id)
            if payload:
                saved = SavedEpicConnection.model_validate(payload)
                if saved.binding != self._binding():
                    raise EpicReauthorizationRequired(
                        "Epic authorization settings changed. Reauthorize this patient "
                        "to request the current Clinical and Claims permissions."
                    )
                token = saved.token
                self._validate_token(token, saved.patient_id)
                self._sessions[session_id] = EpicSession(
                    patient_id=saved.patient_id,
                    smart=saved.smart,
                    state="",
                    verifier="",
                    token=token,
                    expires_at=saved.expires_at,
                    connection_expires_at=saved.connection_expires_at,
                )
        try:
            session = self._sessions[session_id]
        except KeyError:
            raise EpicReauthorizationRequired(
                "Epic patient authorization is unavailable. Reauthorize this patient."
            ) from None
        if (
            session.connection_expires_at
            and session.connection_expires_at <= time.time()
        ):
            self.end_session(session_id)
            raise EpicReauthorizationRequired(
                "Epic patient authorization expired. Reauthorize this patient."
            )
        return session

    @staticmethod
    def _validate_patient(session: EpicSession, patient_id: str) -> None:
        if session.patient_id != patient_id:
            raise EpicReauthorizationRequired(
                "Epic authorization does not match the selected patient. "
                "Reauthorize this patient."
            )

    @staticmethod
    def _validate_token(token: EpicToken, patient_id: str) -> int:
        if token.patient != patient_id:
            raise EpicReauthorizationRequired(
                "Epic authorization does not match the selected patient. "
                "Reauthorize this patient."
            )
        if token.expires_in is None or token.expires_in <= 0:
            raise EpicReauthorizationRequired(
                "Epic authorization is invalid. Reauthorize this patient."
            )
        return token.expires_in

    @staticmethod
    def _config() -> EpicConfig:
        return EpicConfig.from_environment().model_copy(
            update={"scope": MEDICATION_REVIEW_SCOPE}
        )

    @staticmethod
    def _patient_search_config() -> EpicConfig:
        return EpicConnector._config().model_copy(update={"scope": DEFAULT_EPIC_SCOPE})


def create_connector() -> EpicConnector:
    return EpicConnector()


def patient_search_result(result: EpicPatientSearchResult) -> PatientSearchResult:
    candidates = []
    for patient in result.patients:
        name = patient.primary_name
        candidates.append(
            PatientSearchCandidate(
                patient_id=patient.id,
                given_name=" ".join(name.given).strip() or None if name else None,
                family_name=name.family.strip() or None if name else None,
                birth_date=patient.birth_date,
            )
        )
    return PatientSearchResult(
        candidates=candidates,
        total=result.total,
        more_matches_available=result.more_matches_available,
    )
