import asyncio
import logging
import shutil
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from openai import APIConnectionError

from folium_agents.api import app as api
from folium_agents.api.models import ChatMessage
from folium_agents.core.connections import ConnectionStore
from folium_agents.epic.adapter import EpicConnector
from folium_agents.epic.epic import EpicConfig, EpicSmartClient
from folium_agents.epic.models import EpicToken, SmartConfiguration


@pytest.fixture
def persistent_connections(monkeypatch: pytest.MonkeyPatch):
    directory = Path(".test-connections") / uuid4().hex
    directory.mkdir(parents=True)
    monkeypatch.setenv("FOLIUM_AGENTS_CONNECTION_DB", str(directory / "state.sqlite3"))
    monkeypatch.setenv("FOLIUM_AGENTS_CONNECTION_KEY_FILE", str(directory / "key"))
    store = ConnectionStore(directory / "state.sqlite3", directory / "key")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "sessions", {})
    config = EpicConfig(
        _env_file=None,
        client_id="synthetic-client",
        redirect_uri="https://app.example.test/api/epic/callback",
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
        )

    monkeypatch.setattr(EpicSmartClient, "discover", discover)
    monkeypatch.setattr(EpicSmartClient, "exchange_code", exchange)
    connector = EpicConnector()
    monkeypatch.setattr(api, "connectors", {"epic": connector})
    try:
        yield directory, store, connector
    finally:
        shutil.rmtree(directory)
        if directory.parent.exists() and not any(directory.parent.iterdir()):
            directory.parent.rmdir()


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
    monkeypatch.setattr(api, "connectors", {"epic": restored})
    for session_id, patient in (
        (first, "synthetic-patient-a"),
        (second, "synthetic-patient-b"),
    ):
        response = client.get(f"/api/sessions/{session_id}")
        assert response.json() == {"connected": True, "patientId": patient}
    assert api.sessions[first].messages == []
    with pytest.raises(ValueError, match="did not match"):
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
    assert client.delete(f"/api/sessions/{first}").status_code == 204
    api.sessions.clear()
    monkeypatch.setattr(api, "connectors", {"epic": EpicConnector()})
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

        async def retrieve_from_model(_messages, retrieve):
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
    monkeypatch.setattr(api, "connectors", {"epic": connector})
    config = EpicConfig(
        _env_file=None,
        client_id="different-synthetic-client",
        redirect_uri="https://app.example.test/api/epic/callback",
    )
    monkeypatch.setattr(EpicConnector, "_config", staticmethod(lambda: config))
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
