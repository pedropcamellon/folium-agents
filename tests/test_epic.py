import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import ValidationError

from folium_agents.epic import EpicConfig, EpicSmartClient, SmartConfiguration


def test_epic_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPIC_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv(
        "EPIC_REDIRECT_URI",
        "https://agents.example.test/oauth/callback",
    )
    monkeypatch.setenv("EPIC_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("EPIC_TOKEN_AUTH_METHOD", "client_secret_post")

    config = EpicConfig.from_environment()

    assert config.client_id == "sandbox-client"
    assert config.redirect_uri == "https://agents.example.test/oauth/callback"
    assert config.client_secret is not None
    assert "synthetic-secret" not in repr(config)
    assert config.token_auth_method == "client_secret_post"


def test_epic_settings_require_client_id_and_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EPIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("EPIC_REDIRECT_URI", raising=False)

    with pytest.raises(ValidationError, match="client_id|redirect_uri"):
        EpicConfig(_env_file=None)


def test_build_authorization_url_includes_state_pkce_and_launch_context() -> None:
    config = EpicConfig(
        client_id="sandbox-client",
        redirect_uri="https://agents.example.test/oauth/callback",
    )
    client = EpicSmartClient(config)
    smart = SmartConfiguration(
        authorization_endpoint="https://epic.example.test/oauth/authorize",
        token_endpoint="https://epic.example.test/oauth/token",
        code_challenge_methods_supported=["S256"],
    )
    verifier, challenge = client.create_pkce_pair()
    state = client.create_state()

    url = client.build_authorization_url(
        smart,
        state=state,
        code_challenge=challenge,
        issuer="https://epic.example.test/api/FHIR/R4",
        launch="synthetic-launch",
    )
    query = parse_qs(urlparse(url).query)

    assert query["client_id"] == ["sandbox-client"]
    assert query["redirect_uri"] == ["https://agents.example.test/oauth/callback"]
    assert query["state"] == [state]
    assert query["code_challenge"] == [challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["launch"] == ["synthetic-launch"]
    assert len(verifier) >= 43


def test_exchange_code_rejects_state_mismatch_before_request() -> None:
    async def run_test() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("state mismatch must not send a request")
            )
        ) as http_client:
            client = EpicSmartClient(
                EpicConfig(
                    client_id="sandbox-client",
                    redirect_uri="https://agents.example.test/oauth/callback",
                ),
                http_client=http_client,
            )
            smart = SmartConfiguration(
                authorization_endpoint="https://epic.example.test/oauth/authorize",
                token_endpoint="https://epic.example.test/oauth/token",
                code_challenge_methods_supported=["S256"],
            )
            with pytest.raises(ValueError, match="state mismatch"):
                await client.exchange_code(
                    smart,
                    code="authorization-code",
                    returned_state="wrong-state",
                    expected_state="expected-state",
                    code_verifier="verifier",
                )

    asyncio.run(run_test())


def test_exchange_code_posts_verifier_and_parses_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "synthetic-access-token",
                "token_type": "Bearer",
                "expires_in": 300,
                "patient": "synthetic-patient",
                "encounter": "synthetic-encounter",
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                EpicConfig(
                    client_id="sandbox-client",
                    redirect_uri="https://agents.example.test/oauth/callback",
                ),
                http_client=client,
            )
            smart = SmartConfiguration(
                authorization_endpoint="https://epic.example.test/oauth/authorize",
                token_endpoint="https://epic.example.test/oauth/token",
                code_challenge_methods_supported=["S256"],
            )
            token = await epic.exchange_code(
                smart,
                code="synthetic-code",
                returned_state="state",
                expected_state="state",
                code_verifier="pkce-verifier",
            )

        assert token.access_token == "synthetic-access-token"
        assert token.patient == "synthetic-patient"
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert b"code_verifier=pkce-verifier" in requests[0].content
        assert b"client_secret" not in requests[0].content

    asyncio.run(run_test())


def test_get_care_plan_requests_only_minimal_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "resourceType": "CarePlan",
                "id": "synthetic-care-plan",
                "status": "active",
                "subject": {"reference": "Patient/synthetic-patient"},
                "encounter": {"reference": "Encounter/synthetic-encounter"},
                "description": "Should not be returned by the typed summary.",
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                EpicConfig(
                    client_id="sandbox-client",
                    redirect_uri="https://agents.example.test/oauth/callback",
                    issuer="https://epic.example.test/api/FHIR/R4",
                ),
                http_client=client,
            )
            care_plan = await epic.get_care_plan(
                "synthetic-token",
                "synthetic-care-plan",
            )

        assert care_plan.id == "synthetic-care-plan"
        assert care_plan.status == "active"
        assert len(requests) == 1
        assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
        assert requests[0].url.params["_elements"] == "id,status,subject,encounter"

    asyncio.run(run_test())
