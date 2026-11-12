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
    AuthorizationRequest,
    ChartEvidence,
    EHRConnectionStatus,
    EvidenceRecord,
    PatientDemographics,
)
from folium_agents.epic.epic import MEDICATION_REVIEW_SCOPE, EpicConfig, EpicSmartClient
from folium_agents.epic.models import EpicToken, SmartConfiguration


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


class EpicConnector:
    name = "epic"

    def __init__(self) -> None:
        self._sessions: dict[str, EpicSession] = {}
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
        self._validate_token(token, session.patient_id)
        session.token = token
        session.expires_at = time.time() + token.expires_in
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

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self._store:
            self._store.delete("epic", session_id)

    async def _access_token(self, session: EpicSession) -> EpicToken:
        async with self._refresh_lock:
            return await self._refresh_token(session)

    async def _refresh_token(self, session: EpicSession) -> EpicToken:
        if (
            session.token is not None
            and session.expires_at is not None
            and session.expires_at > time.time() + 30
        ):
            return session.token
        if session.token is None or not session.token.refresh_token:
            session.token = None
            self._discard_token(session)
            diagnostic("oauth.reauthorization_required")
            raise ValueError(
                "Epic authorization expired. Start a new chat session to reconnect."
            )
        previous = session.token
        diagnostic("oauth.refresh_started")
        try:
            token = await EpicSmartClient(self._config()).refresh_access_token(
                session.smart,
                previous.refresh_token,
            )
        except httpx.HTTPStatusError as error:
            diagnostic("oauth.refresh_failed", error=error)
            if error.response.status_code in {400, 401}:
                session.token = None
                self._discard_token(session)
                raise ValueError(
                    "Epic refresh authorization was rejected. Start a new chat "
                    "session to reconnect."
                ) from error
            raise
        if token.patient is None:
            token.patient = previous.patient
        if token.refresh_token is None:
            token.refresh_token = previous.refresh_token
        try:
            self._validate_token(token, session.patient_id)
        except ValueError:
            session.token = None
            self._discard_token(session)
            raise
        session.token = token
        session.expires_at = time.time() + token.expires_in
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
                    raise ValueError("Connection configuration changed; reconnect.")
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
            raise ValueError("Epic connection session is unavailable.") from None
        if (
            session.connection_expires_at
            and session.connection_expires_at <= time.time()
        ):
            self.end_session(session_id)
            raise ValueError("Epic connection expired; reconnect.")
        return session

    @staticmethod
    def _validate_patient(session: EpicSession, patient_id: str) -> None:
        if session.patient_id != patient_id:
            raise ValueError("FHIR request patient did not match active context.")

    @staticmethod
    def _validate_token(token: EpicToken, patient_id: str) -> None:
        if token.patient != patient_id:
            raise ValueError("Authorized Epic patient did not match selected context.")
        if token.expires_in is None or token.expires_in <= 0:
            raise ValueError("Epic returned a token without a valid lifetime.")

    @staticmethod
    def _config() -> EpicConfig:
        return EpicConfig.from_environment().model_copy(
            update={"scope": MEDICATION_REVIEW_SCOPE}
        )


def create_connector() -> EpicConnector:
    return EpicConnector()
