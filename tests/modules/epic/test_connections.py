import asyncio
import logging
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from openai import APIConnectionError

from folium_agents.api import app as api
from folium_agents.api.models import ChatMessage
from folium_agents.core.connections import ConnectionStore
from folium_agents.core.ehr import (
    AuthorizationRequest,
    EHRProvider,
    PatientSearchCandidate,
    PatientSearchCriteria,
    PatientSearchResult,
)
from folium_agents.epic.adapter import EpicConnector
from folium_agents.epic.epic import (
    MEDICATION_REVIEW_SCOPE,
    EpicConfig,
    EpicPatientSearchRejected,
    EpicSmartClient,
)
from folium_agents.epic.models import (
    EpicPatient,
    EpicPatientSearchResult,
    EpicToken,
    SmartConfiguration,
)


@pytest.fixture
def persistent_connections(monkeypatch: pytest.MonkeyPatch):
    directory = Path(".test-connections") / uuid4().hex
    directory.mkdir(parents=True)
    monkeypatch.setenv("FOLIUM_AGENTS_CONNECTION_DB", str(directory / "state.sqlite3"))
    monkeypatch.setenv("FOLIUM_AGENTS_CONNECTION_KEY_FILE", str(directory / "key"))
    store = ConnectionStore(directory / "state.sqlite3", directory / "key")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "sessions", {})
    monkeypatch.setattr(api, "patient_search_sessions", {})
    config = EpicConfig(
        _env_file=None,
        client_id="synthetic-client",
        redirect_uri="https://app.example.test/api/epic/callback",
        scope=MEDICATION_REVIEW_SCOPE,
    )
    monkeypatch.setattr(EpicConnector, "_config", staticmethod(lambda: config))

    async def discover(_self):
        return SmartConfiguration(
            authorization_endpoint="https://ehr.example.test/authorize",
            token_endpoint="https://ehr.example.test/token",
            code_challenge_methods_supported=["S256"],
        )

    async def exchange(_self, _smart, **kwargs):
        return EpicToken(
            access_token=f"secret-access-{kwargs['code']}",
            refresh_token=f"secret-refresh-{kwargs['code']}",
            patient=kwargs["code"],
            expires_in=3600,
            scope=(
                "openid fhirUser user/ExplanationOfBenefit.r "
                "user/ExplanationOfBenefit.s"
            ),
        )

    monkeypatch.setattr(EpicSmartClient, "discover", discover)
    monkeypatch.setattr(EpicSmartClient, "exchange_code", exchange)
    connector = EpicConnector()
    monkeypatch.setattr(api, "connectors", {"epic": _epic_provider(connector)})
    try:
        yield directory, store, connector
    finally:
        shutil.rmtree(directory)
        if directory.parent.exists() and not any(directory.parent.iterdir()):
            directory.parent.rmdir()


def _epic_provider(connector: EpicConnector) -> EHRProvider:
    return EHRProvider(
        provider_id="epic",
        connector=connector,
        patient_search=connector,
        claims=connector,
    )


def authorize(client: TestClient, patient: str) -> str:
    response = client.post("/api/sessions", json={"patientId": patient})
    assert response.status_code == 200
    session_id = response.json()["sessionId"]
    state = api.sessions[session_id].authorization_state
    callback = client.get(
        "/api/epic/callback",
        params={"state": state, "code": patient},
        follow_redirects=False,
    )
    assert callback.status_code == 307
    return session_id


def test_patient_authorization_requests_combined_explicit_scopes(
    persistent_connections,
) -> None:
    client = TestClient(api.app)
    response = client.post(
        "/api/sessions",
        json={"patientId": "synthetic-patient-a"},
    )
    assert response.status_code == 200
    authorization_url = response.json()["authorizationUrl"]
    scopes = parse_qs(urlparse(authorization_url).query)["scope"][0].split()
    assert scopes == MEDICATION_REVIEW_SCOPE.split()
    assert "patient/MedicationRequest.rs" in scopes
    assert "user/ExplanationOfBenefit.rs" in scopes
    assert not any(scope.startswith("system/") for scope in scopes)


def test_provider_patient_search_authorization_and_selection_flow(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(api.app)
    created = client.post("/api/patient-search/sessions")
    assert created.status_code == 200
    session_id = created.json()["sessionId"]
    authorization_url = created.json()["authorizationUrl"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["scope"] == ["openid fhirUser user/Patient.rs"]
    assert "launch" not in query

    state = api.patient_search_sessions[session_id].authorization_state

    async def exchange(_self, _smart, **_kwargs):
        return EpicToken(
            access_token="synthetic-provider-token",
            expires_in=3600,
            patient=None,
            scope="openid fhirUser user/Patient.rs",
        )

    calls: list[tuple[str, str, str, str]] = []

    async def search(
        _self,
        access_token: str,
        *,
        patient_id: str | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        birthdate: str | None = None,
        issuer: str | None = None,
    ) -> EpicPatientSearchResult:
        assert access_token == "synthetic-provider-token"
        assert issuer is None
        assert patient_id is None
        calls.append(
            (access_token, given_name or "", family_name or "", birthdate or "")
        )
        return EpicPatientSearchResult(
            total=1,
            patients=[
                EpicPatient(
                    resourceType="Patient",
                    id="synthetic-patient-a",
                    name=[{"given": ["Alex"], "family": "Sample"}],
                    birthDate="1980-01-01",
                )
            ],
        )

    monkeypatch.setattr(EpicSmartClient, "exchange_code", exchange)
    monkeypatch.setattr(EpicSmartClient, "search_patients", search)
    callback = client.get(
        "/api/epic/callback",
        params={"state": state, "code": "provider-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 307
    assert "patient_search_session_id=" in callback.headers["location"]

    response = client.post(
        f"/api/patient-search/sessions/{session_id}/search",
        json={
            "givenName": "Alex",
            "familyName": "Sam",
            "birthDate": "1980-01-01",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [
            {
                "patientId": "synthetic-patient-a",
                "givenName": "Alex",
                "familyName": "Sample",
                "birthDate": "1980-01-01",
            }
        ],
        "total": 1,
        "moreMatchesAvailable": False,
    }
    assert calls == [("synthetic-provider-token", "Alex", "Sam", "1980-01-01")]


def test_patient_search_routes_use_the_provider_capability_contract(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePatientSearchProvider:
        name = "synthetic"

        async def start_patient_search_authorization(
            self, session_id: str
        ) -> AuthorizationRequest:
            assert session_id
            return AuthorizationRequest(
                state="synthetic-state",
                authorization_url="https://provider.example.test/authorize",
            )

        async def complete_patient_search_authorization(
            self, session_id: str, *, state: str, code: str
        ) -> None:
            assert session_id
            assert state == "synthetic-state"
            assert code == "synthetic-code"

        async def search_patient_candidates(
            self, session_id: str, criteria: PatientSearchCriteria
        ) -> PatientSearchResult:
            assert session_id
            assert criteria == PatientSearchCriteria(
                given_name="Alex",
                family_name="Sample",
                birth_date="1980-01-01",
            )
            return PatientSearchResult(
                candidates=[
                    PatientSearchCandidate(
                        patient_id="synthetic-patient",
                        given_name="Alex",
                        family_name="Sample",
                        birth_date="1980-01-01",
                    )
                ],
                total=1,
                more_matches_available=False,
            )

        def end_patient_search_session(self, session_id: str) -> None:
            return None

    search_provider = FakePatientSearchProvider()
    monkeypatch.setattr(
        api,
        "connectors",
        {
            "synthetic": EHRProvider(
                provider_id="synthetic",
                connector=None,
                patient_search=search_provider,
                claims=None,
            )
        },
    )
    monkeypatch.setattr(api.settings, "patient_search_provider", "synthetic")
    client = TestClient(api.app)
    created = client.post("/api/patient-search/sessions")
    assert created.status_code == 200
    session_id = created.json()["sessionId"]

    callback = client.get(
        "/api/synthetic/callback",
        params={"state": "synthetic-state", "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 307

    response = client.post(
        f"/api/patient-search/sessions/{session_id}/search",
        json={
            "givenName": "Alex",
            "familyName": "Sample",
            "birthDate": "1980-01-01",
        },
    )

    assert response.status_code == 200
    assert response.json()["candidates"][0]["patientId"] == "synthetic-patient"
    ended = client.delete(f"/api/patient-search/sessions/{session_id}")
    assert ended.status_code == 204


def test_patient_search_requires_demographic_input(
    persistent_connections,
) -> None:
    session_id = "synthetic-search-session"
    api.patient_search_sessions[session_id] = api.PatientSearchSessionState(
        provider_id="epic",
        authorization_state="",
    )
    response = TestClient(api.app).post(
        f"/api/patient-search/sessions/{session_id}/search",
        json={
            "givenName": " ",
            "familyName": "Sample",
            "birthDate": "1980-01-01",
        },
    )

    assert response.status_code == 422


def test_patient_search_maps_epic_outcome_to_demographic_guidance(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(api.app)
    created = client.post("/api/patient-search/sessions")
    session_id = created.json()["sessionId"]
    state = api.patient_search_sessions[session_id].authorization_state

    async def exchange(_self, _smart, **_kwargs):
        return EpicToken(
            access_token="synthetic-provider-token",
            expires_in=3600,
            patient=None,
            scope="openid fhirUser user/Patient.rs",
        )

    async def reject_search(*_args, **_kwargs):
        raise EpicPatientSearchRejected(
            "Epic could not return patient candidates. Check your "
            "organization's minimum demographics and Patient.Search "
            "support or configuration.",
            provider_issue_codes=("required", "patient-specific-detail"),
            provider_issue_severities=("error", "patient-specific-detail"),
        )

    monkeypatch.setattr(EpicSmartClient, "exchange_code", exchange)
    monkeypatch.setattr(EpicSmartClient, "search_patients", reject_search)
    callback = client.get(
        "/api/epic/callback",
        params={"state": state, "code": "provider-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 307

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        response = client.post(
            f"/api/patient-search/sessions/{session_id}/search",
            json={
                "givenName": "Sample",
                "familyName": "Patient",
                "birthDate": "1980-01-01",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "The provider rejected the patient search. Check its search "
        "requirements and Patient.Search access."
    )
    assert '"provider_issue_codes": ["required"]' in caplog.text
    assert '"provider_issue_severities": ["error"]' in caplog.text
    assert "patient-specific-detail" not in caplog.text


@pytest.mark.parametrize(
    ("patient", "scope"),
    [
        ("synthetic-patient", "openid fhirUser user/Patient.rs"),
        (None, "openid fhirUser user/Patient.s"),
        (None, "openid fhirUser user/Patient.r"),
    ],
)
def test_patient_search_rejects_patient_bound_or_incomplete_provider_grants(
    patient: str | None,
    scope: str,
) -> None:
    with pytest.raises(ValueError):
        EpicConnector._validate_search_token(
            EpicToken(
                access_token="synthetic-token",
                patient=patient,
                expires_in=3600,
                scope=scope,
            )
        )


def test_patient_claim_search_uses_shared_session_and_all_dates(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folium_agents.epic import financial_reads

    session_id = authorize(TestClient(api.app), "synthetic-patient-a")
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params.get_list("patient") == ["synthetic-patient-a"]
        assert "created" not in request.url.params
        if len(calls) == 1:
            assert request.url.params.get("use") == "claim"
        claim_id = f"CLAIM-{len(calls)}"
        created = "2010-03-05" if len(calls) == 1 else "2026-01-15"
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 2,
            "entry": [
                {
                    "resource": {
                        "resourceType": "ExplanationOfBenefit",
                        "use": "claim",
                        "id": claim_id,
                        "status": "active",
                        "created": created,
                        "patient": {"reference": "Patient/synthetic-patient-a"},
                        "total": [],
                    }
                }
            ],
        }
        if len(calls) == 1:
            bundle["link"] = [
                {
                    "relation": "next",
                    "url": (
                        "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/"
                        "ExplanationOfBenefit?patient=synthetic-patient-a&page=2"
                    ),
                }
            ]
        return httpx.Response(
            200,
            json=bundle,
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        financial_reads.httpx,
        "AsyncClient",
        lambda: original(transport=httpx.MockTransport(handle)),
    )
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")
    assert response.status_code == 200
    assert response.json()["patientId"] == "synthetic-patient-a"
    assert response.json()["pages"] == 2
    assert response.json()["complete"] is True
    assert [claim["created"] for claim in response.json()["claims"]] == [
        "2010-03-05",
        "2026-01-15",
    ]
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("patient", "use"),
    [
        ("synthetic-patient-b", "claim"),
        ("synthetic-patient-a", "preauthorization"),
    ],
)
def test_patient_claim_search_rejects_wrong_patient_or_nonclaim_eob(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
    patient: str,
    use: str,
) -> None:
    from folium_agents.epic import financial_reads

    session_id = authorize(TestClient(api.app), "synthetic-patient-a")

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "ExplanationOfBenefit",
                            "use": use,
                            "id": "CLAIM-OTHER",
                            "status": "active",
                            "created": "2010-03-05",
                            "patient": {"reference": f"Patient/{patient}"},
                        }
                    }
                ],
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        financial_reads.httpx,
        "AsyncClient",
        lambda: original(transport=httpx.MockTransport(handle)),
    )
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")
    assert response.status_code == 424
    assert "claims" not in response.json()


@pytest.mark.parametrize(
    "scope",
    [
        "openid user/Patient.r",
        "user/ExplanationOfBenefit.r",
        "user/ExplanationOfBenefit.s",
    ],
)
def test_patient_claim_search_reports_missing_eob_permissions(
    persistent_connections,
    scope: str,
) -> None:
    session_id = authorize(TestClient(api.app), "synthetic-patient-a")
    provider = api.connectors["epic"]
    connector = provider.connector
    assert isinstance(connector, EpicConnector)
    token = connector._sessions[session_id].token
    assert token is not None
    token.scope = scope

    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")

    assert response.status_code == 424
    assert (
        "missing ExplanationOfBenefit read and search permissions"
        in response.json()["detail"]
    )


def test_claim_pagination_rejects_a_prior_authorization_filter() -> None:
    from folium_agents.epic.financial_reads import FinancialReadError, next_page_url

    base = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
    with pytest.raises(FinancialReadError, match="non-claim pagination"):
        next_page_url(
            base,
            f"{base}/ExplanationOfBenefit",
            "?patient=synthetic-patient-a&use=preauthorization",
            "synthetic-patient-a",
        )


def test_patient_claim_search_reports_stale_scope_binding(
    persistent_connections,
) -> None:
    _directory, store, _connector = persistent_connections
    session_id = authorize(TestClient(api.app), "synthetic-patient-a")
    saved = store.load("epic", session_id)
    assert saved is not None
    saved["binding"] = "previous-scope-binding"
    store.save("epic", session_id, saved, saved["connection_expires_at"])
    api.connectors["epic"] = _epic_provider(EpicConnector())

    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")

    assert response.status_code == 401
    assert "authorization settings changed" in response.json()["detail"]
    assert "Patient claim access is unavailable" not in response.json()["detail"]


def test_patient_claim_search_reports_invalid_claim_date(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folium_agents.epic import financial_reads

    session_id = authorize(TestClient(api.app), "synthetic-patient-a")

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "ExplanationOfBenefit",
                            "use": "claim",
                            "id": "CLAIM-INVALID-DATE",
                            "status": "active",
                            "created": "not-a-date",
                            "patient": {"reference": "Patient/synthetic-patient-a"},
                            "total": [],
                        }
                    }
                ],
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        financial_reads.httpx,
        "AsyncClient",
        lambda: original(transport=httpx.MockTransport(handle)),
    )
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")

    assert response.status_code == 424
    assert "invalid claim date" in response.json()["detail"]
    assert "Reauthorize" not in response.json()["detail"]


@pytest.mark.parametrize(
    ("severity", "code", "epic_code", "total", "expected_status", "message"),
    [
        (
            "warning",
            "suppressed",
            "59205",
            0,
            424,
            "Epic suppressed claim search results",
        ),
        ("warning", "processing", "4101", 0, 200, "no matching claims"),
        ("warning", "processing", "4101", 1, 424, "processing or access warning"),
        ("warning", "processing", "unknown", 0, 424, "processing or access warning"),
        ("warning", "processing", None, 0, 424, "processing or access warning"),
        ("error", "processing", "4101", 0, 424, "processing or access warning"),
        (
            "information",
            "informational",
            None,
            0,
            200,
            "informational claim search outcome",
        ),
    ],
)
def test_patient_claim_search_handles_bundled_operation_outcomes(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    code: str,
    epic_code: str | None,
    total: int,
    expected_status: int,
    message: str,
) -> None:
    from folium_agents.epic import financial_reads

    session_id = authorize(TestClient(api.app), "synthetic-patient-a")

    def handle(_request: httpx.Request) -> httpx.Response:
        assert _request.url.params["use"] == "claim"
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "total": total,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "OperationOutcome",
                            "issue": [
                                {
                                    "severity": severity,
                                    "code": code,
                                    "details": {
                                        "coding": [{"code": epic_code}]
                                        if epic_code
                                        else [],
                                    },
                                    "diagnostics": "untrusted-provider-detail-do-not-display",
                                }
                            ],
                        }
                    }
                ],
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        financial_reads.httpx,
        "AsyncClient",
        lambda: original(transport=httpx.MockTransport(handle)),
    )
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/financial/claims")
    assert response.status_code == expected_status
    assert "untrusted-provider-detail" not in response.text
    if expected_status == 200:
        assert response.json()["claims"] == []
        assert response.json()["complete"] is True
        assert any(message in item for item in response.json()["limitations"])
    else:
        assert message in response.json()["detail"]
        assert "claims" not in response.json()


def test_restart_isolation_refresh_and_local_revocation(
    persistent_connections,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, store, _connector = persistent_connections
    client = TestClient(api.app)
    first = authorize(client, "synthetic-patient-a")
    second = authorize(client, "synthetic-patient-b")
    api.sessions[first].messages.append(
        ChatMessage(role="user", content="secret-chart-text")
    )
    disk = (directory / "state.sqlite3").read_bytes()
    for secret in (
        first,
        second,
        "synthetic-patient",
        "secret-access",
        "secret-refresh",
        "secret-chart-text",
    ):
        assert secret.encode() not in disk
    assert store.load("api", first).get("messages") is None

    api.sessions.clear()
    restored = EpicConnector()
    monkeypatch.setattr(api, "connectors", {"epic": _epic_provider(restored)})
    for session_id, patient in (
        (first, "synthetic-patient-a"),
        (second, "synthetic-patient-b"),
    ):
        response = client.get(f"/api/sessions/{session_id}")
        assert response.json() == {
            "connected": True,
            "patientId": patient,
            "authorizationState": "authorized",
            "supportedOperations": ["patient_search", "patient_chat", "claims"],
        }
    assert api.sessions[first].messages == []
    with pytest.raises(ValueError, match="authorization does not match"):
        asyncio.run(restored.get_connection_status(first, "synthetic-patient-b"))

    refreshes = []

    async def refresh(_self, _smart, refresh_token):
        refreshes.append(refresh_token)
        # Some providers omit patient/refresh_token on a refresh response.
        return EpicToken(access_token="rotated-access", expires_in=3600)

    monkeypatch.setattr(EpicSmartClient, "refresh_access_token", refresh)
    restored._sessions[first].expires_at = time.time() - 1
    assert client.get(f"/api/sessions/{first}").json()["connected"]
    assert refreshes == ["secret-refresh-synthetic-patient-a"]
    saved = store.load("epic", first)
    assert saved["token"]["access_token"] == "rotated-access"
    assert saved["token"]["refresh_token"] == "secret-refresh-synthetic-patient-a"
    assert saved["token"]["scope"] == (
        "openid fhirUser user/ExplanationOfBenefit.r user/ExplanationOfBenefit.s"
    )
    assert client.delete(f"/api/sessions/{first}").status_code == 204
    api.sessions.clear()
    monkeypatch.setattr(
        api, "connectors", {"epic": _epic_provider(EpicConnector())}
    )
    assert client.get(f"/api/sessions/{first}").status_code == 404
    assert client.get(f"/api/sessions/{second}").json()["connected"]


def test_refresh_rejection_is_not_restored(persistent_connections, monkeypatch):
    _, store, connector = persistent_connections
    client = TestClient(api.app)
    session_id = authorize(client, "synthetic-patient-a")
    connector._sessions[session_id].expires_at = time.time() - 1

    async def rejected(*_args):
        response = httpx.Response(
            400, request=httpx.Request("POST", "https://ehr.example.test/token")
        )
        raise httpx.HTTPStatusError(
            "secret-provider-body", request=response.request, response=response
        )

    monkeypatch.setattr(EpicSmartClient, "refresh_access_token", rejected)
    assert client.get(f"/api/sessions/{session_id}").json()["connected"] is False
    assert store.load("epic", session_id) is None
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(
            EpicConnector().get_connection_status(session_id, "synthetic-patient-a")
        )


def test_expiry_pending_authorization_and_wrong_key_fail_closed(persistent_connections):
    directory, store, _ = persistent_connections
    client = TestClient(api.app)
    session_id = authorize(client, "synthetic-patient-a")
    api.sessions[session_id].created_at -= api.SESSION_TTL_SECONDS + 1
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert store.load("api", session_id) is None
    assert store.load("epic", session_id) is None
    pending = client.post(
        "/api/sessions", json={"patientId": "synthetic-patient-b"}
    ).json()["sessionId"]
    assert store.load("api", pending) is None
    store.save("test", "synthetic-session", {"token": "secret"}, time.time() + 60)
    wrong_key = directory / "wrong-key"
    wrong_key.write_bytes(Fernet.generate_key())
    wrong_key.chmod(0o600)
    wrong_store = ConnectionStore(directory / "state.sqlite3", wrong_key)
    with pytest.raises(InvalidToken):
        wrong_store.load("test", "synthetic-session")
    store.save("test", "expired-session", {}, time.time() - 1)
    assert store.load("test", "expired-session") is None


@pytest.mark.parametrize("failure", ["model_connection", "validation", "fhir"])
def test_redacted_correlated_diagnostics(
    persistent_connections,
    monkeypatch,
    caplog,
    failure,
):
    _, _, connector = persistent_connections
    client = TestClient(api.app)
    session_id = authorize(client, "synthetic-patient-a")
    secret = "secret-validation-chart-code-access-refresh"

    async def fail(*_args):
        if failure == "model_connection":
            raise APIConnectionError(
                message=secret,
                request=httpx.Request("POST", f"https://model.example.test/{secret}"),
            )
        if failure == "fhir":
            response = httpx.Response(
                403, request=httpx.Request("GET", f"https://ehr.example.test/{secret}")
            )
            raise httpx.HTTPStatusError(
                secret, request=response.request, response=response
            )
        raise ValueError(secret)

    if failure == "fhir":

        async def retrieve_from_model(_messages, retrieve, _retrieve_claims=None):
            return await retrieve()

        monkeypatch.setattr(connector, "retrieve_patient_chart", fail)
        monkeypatch.setattr(api, "_ask_model", retrieve_from_model)
    else:
        monkeypatch.setattr(api, "_ask_model", fail)
    caplog.set_level(logging.INFO)
    caplog.clear()
    response = client.post(
        f"/api/sessions/{session_id}/chat", json={"question": secret}
    )
    assert response.status_code == 502
    reference = response.headers["X-Correlation-ID"]
    assert len(reference) == 32
    assert reference in caplog.text
    assert "chat.model_or_validation_failed" in caplog.text
    if failure == "fhir":
        assert "fhir.retrieval_failed" in caplog.text
    assert secret not in caplog.text
    assert session_id not in caplog.text
    assert "synthetic-patient-a" not in caplog.text
    assert secret not in response.text


def test_oauth_errors_and_validation_inputs_are_not_logged(
    persistent_connections, monkeypatch, caplog
):
    _, _, connector = persistent_connections
    client = TestClient(api.app)
    secret = "secret-provider-error-and-code"

    async def fail(*_args):
        raise ValueError(secret)

    monkeypatch.setattr(connector, "start_authorization", fail)
    caplog.clear()
    response = client.post("/api/sessions", json={"patientId": "synthetic-patient-a"})
    assert response.status_code == 502
    assert "oauth.start_failed" in caplog.text
    assert secret not in caplog.text + response.text
    assert (
        client.post("/api/sessions", json={"patientId": {"secret": secret}}).status_code
        == 422
    )
    assert secret not in caplog.text


def test_callback_patient_mismatch_and_denial_do_not_persist(
    persistent_connections,
    caplog,
):
    _, store, _ = persistent_connections
    client = TestClient(api.app)
    caplog.set_level(logging.INFO)
    for denied in (False, True):
        created = client.post(
            "/api/sessions", json={"patientId": "synthetic-patient-a"}
        )
        session_id = created.json()["sessionId"]
        state = api.sessions[session_id].authorization_state
        query = {"state": state}
        query.update(
            {"error": "secret-provider-error"}
            if denied
            else {"code": "synthetic-patient-b"}
        )
        response = client.get("/api/epic/callback", params=query)
        assert response.status_code == (400 if denied else 502)
        assert store.load("api", session_id) is None
        assert store.load("epic", session_id) is None
        assert session_id not in api.sessions
        assert session_id not in caplog.text
        assert state not in caplog.text
    assert "secret-provider-error" not in caplog.text
    assert "synthetic-patient-b" not in caplog.text


@pytest.mark.parametrize(
    "failure", ["no_refresh", "patient_mismatch", "transient", "rotation", "fhir_401"]
)
def test_token_lifecycle(persistent_connections, monkeypatch, failure):
    _, store, connector = persistent_connections
    client = TestClient(api.app)
    session_id = authorize(client, "synthetic-patient-a")
    session = connector._sessions[session_id]
    session.expires_at = time.time() - 1

    async def refresh(*_args):
        if failure == "transient":
            raise httpx.ConnectError("secret-transient-failure")
        return EpicToken(
            access_token="synthetic-new-access",
            expires_in=3600,
            refresh_token="synthetic-rotated-refresh",
            patient="synthetic-patient-b"
            if failure == "patient_mismatch"
            else "synthetic-patient-a",
        )

    monkeypatch.setattr(EpicSmartClient, "refresh_access_token", refresh)
    if failure == "no_refresh":
        session.token.refresh_token = None
    if failure == "fhir_401":
        session.expires_at = time.time() + 3600

        async def rejected(*_args, **_kwargs):
            response = httpx.Response(
                401, request=httpx.Request("GET", "https://ehr.example.test/Patient")
            )
            raise httpx.HTTPStatusError(
                "secret-fhir-error", request=response.request, response=response
            )

        monkeypatch.setattr(EpicSmartClient, "get_patient", rejected)
        assert client.get(f"/api/sessions/{session_id}/patient").status_code == 502
    response = client.get(f"/api/sessions/{session_id}")
    if failure == "transient":
        assert response.status_code == 502
        assert (
            store.load("epic", session_id)["token"]["refresh_token"]
            == "secret-refresh-synthetic-patient-a"
        )
    elif failure == "rotation":
        assert response.json()["connected"]
        assert (
            store.load("epic", session_id)["token"]["refresh_token"]
            == "synthetic-rotated-refresh"
        )
    else:
        assert response.json()["connected"] is False
        assert store.load("epic", session_id) is None


def test_changed_configuration_rejects_restored_connection(
    persistent_connections,
    monkeypatch,
):
    _, _, _connector = persistent_connections
    client = TestClient(api.app)
    session_id = authorize(client, "synthetic-patient-a")
    api.sessions.clear()
    connector = EpicConnector()
    monkeypatch.setattr(api, "connectors", {"epic": _epic_provider(connector)})
    config = EpicConfig(
        _env_file=None,
        client_id="different-synthetic-client",
        redirect_uri="https://app.example.test/api/epic/callback",
    )
    monkeypatch.setattr(EpicConnector, "_config", staticmethod(lambda: config))
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
