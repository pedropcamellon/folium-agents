import asyncio
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import ValidationError

from folium_agents.epic.epic import (
    CachedEpicToken,
    EpicConfig,
    EpicSmartClient,
    EpicToken,
    EpicTokenCache,
    SmartConfiguration,
)


def _epic_config(**values: object) -> EpicConfig:
    return EpicConfig(_env_file=None, **values)


def test_epic_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPIC_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv(
        "EPIC_REDIRECT_URI",
        "https://agents.example.test/oauth/callback",
    )
    monkeypatch.setenv("EPIC_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("EPIC_TOKEN_AUTH_METHOD", "client_secret_post")

    config = EpicConfig(_env_file=None)

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


def test_epic_settings_load_repository_root_env_file() -> None:
    env_file = EpicConfig.model_config["env_file"]

    assert Path(env_file).resolve() == Path(__file__).resolve().parents[3] / ".env"


def test_build_authorization_url_includes_state_pkce_and_launch_context() -> None:
    config = _epic_config(
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
                _epic_config(
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
                "refresh_token": "synthetic-refresh-token",
                "patient": "synthetic-patient",
                "encounter": "synthetic-encounter",
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                _epic_config(
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
        assert token.refresh_token == "synthetic-refresh-token"
        assert token.patient == "synthetic-patient"
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert b"code_verifier=pkce-verifier" in requests[0].content
        assert b"client_id=sandbox-client" in requests[0].content
        assert b"client_secret" not in requests[0].content
        assert b"client_assertion" not in requests[0].content

    asyncio.run(run_test())


def test_refresh_access_token_posts_refresh_grant_and_preserves_rotation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed-access-token",
                "expires_in": 600,
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                _epic_config(
                    client_id="sandbox-client",
                    redirect_uri="http://localhost:8765/callback",
                ),
                http_client=client,
            )
            token = await epic.refresh_access_token(
                SmartConfiguration(
                    authorization_endpoint="https://epic.example.test/oauth/authorize",
                    token_endpoint="https://epic.example.test/oauth/token",
                    code_challenge_methods_supported=["S256"],
                ),
                "synthetic-refresh-token",
            )

        assert token.access_token == "refreshed-access-token"
        assert token.refresh_token == "synthetic-refresh-token"
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert b"grant_type=refresh_token" in requests[0].content
        assert b"refresh_token=synthetic-refresh-token" in requests[0].content

    asyncio.run(run_test())


def test_epic_token_cache_round_trips_only_through_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folium_agents.epic import epic

    records: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        epic.keyring,
        "get_password",
        lambda service, account: records.get((service, account)),
    )
    monkeypatch.setattr(
        epic.keyring,
        "set_password",
        lambda service, account, value: records.__setitem__(
            (service, account),
            value,
        ),
    )
    monkeypatch.setattr(
        epic.keyring,
        "delete_password",
        lambda service, account: records.pop((service, account)),
    )
    config = _epic_config(
        client_id="sandbox-client",
        redirect_uri="http://localhost:8765/callback",
    )
    cache = EpicTokenCache(config)
    token = EpicToken(
        access_token="synthetic-access-token",
        refresh_token="synthetic-refresh-token",
        expires_in=600,
    )

    cache.save(token)
    cached = cache.load()

    assert cached is not None
    assert isinstance(cached, CachedEpicToken)
    assert cached.is_valid
    assert cached.token == token
    assert len(records) == 1
    cache.clear()
    assert records == {}


def test_discover_fhir_capabilities_reads_metadata_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "resourceType": "CapabilityStatement",
                "status": "active",
                "rest": [
                    {
                        "resource": [
                            {
                                "type": "Patient",
                                "interaction": [{"code": "read"}, {"code": "search-type"}],
                                "searchParam": [
                                    {"name": "_id", "type": "token"},
                                    {"name": "family", "type": "string"},
                                ],
                            }
                        ]
                    }
                ],
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                _epic_config(
                    client_id="sandbox-client",
                    redirect_uri="http://localhost:8765/callback",
                    issuer="https://epic.example.test/api/FHIR/R4",
                ),
                http_client=client,
            )
            capabilities = await epic.discover_fhir_capabilities()

        patient = capabilities.rest[0].resources[0]
        assert patient.resource_type == "Patient"
        assert [item.code for item in patient.interactions] == ["read", "search-type"]
        assert [item.name for item in patient.search_parameters] == ["_id", "family"]
        assert str(requests[0].url) == (
            "https://epic.example.test/api/FHIR/R4/metadata"
        )

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
                _epic_config(
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


def test_search_patients_requests_bounded_minimal_patient_data() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "total": 42,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "sample-001",
                            "name": [{"given": ["Alex"], "family": "Sample"}],
                            "birthDate": "1980-01-01",
                        }
                    }
                ],
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                _epic_config(
                    client_id="sandbox-client",
                    redirect_uri="http://localhost:8765/callback",
                    issuer="https://epic.example.test/api/FHIR/R4",
                ),
                http_client=client,
            )
            result = await epic.search_patients(
                "synthetic-token",
                patient_id="sample-001",
            )

        assert result.total == 42
        assert len(result.patients) == 1
        assert result.patients[0].id == "sample-001"
        assert result.patients[0].display_name == "Alex Sample"
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert str(requests[0].url) == (
            "https://epic.example.test/api/FHIR/R4/Patient"
            "?_id=sample-001"
        )
        assert requests[0].headers["Authorization"] == "Bearer synthetic-token"

    asyncio.run(run_test())


def test_search_patients_includes_epic_operation_outcome_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "error",
                        "code": "invalid",
                        "diagnostics": "Sandbox requires a Patient search filter.",
                    }
                ],
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            epic = EpicSmartClient(
                _epic_config(
                    client_id="sandbox-client",
                    redirect_uri="http://localhost:8765/callback",
                    issuer="https://epic.example.test/api/FHIR/R4",
                ),
                http_client=client,
            )
            with pytest.raises(
                httpx.HTTPStatusError,
                match="Sandbox requires a Patient search filter",
            ):
                await epic.search_patients(
                    "synthetic-token",
                    patient_id="sample-001",
                )

    asyncio.run(run_test())


def test_patient_cli_orchestrates_auth_and_displays_only_patient_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    from folium_agents.epic import epic_cli
    from folium_agents.epic.epic import (
        EpicPatient,
        EpicPatientName,
        EpicPatientSearchResult,
        EpicToken,
    )

    observed: dict[str, object] = {}
    config = _epic_config(
        client_id="sandbox-client",
        redirect_uri="http://localhost:8765/callback",
    )
    smart = SmartConfiguration(
        authorization_endpoint="https://epic.example.test/oauth/authorize",
        token_endpoint="https://epic.example.test/oauth/token",
        code_challenge_methods_supported=["S256"],
    )

    class FakeEpicClient:
        async def discover(self) -> SmartConfiguration:
            return smart

        @staticmethod
        def create_state() -> str:
            return "synthetic-state"

        @staticmethod
        def create_pkce_pair() -> tuple[str, str]:
            return "synthetic-verifier", "synthetic-challenge"

        @staticmethod
        def build_authorization_url(
            discovered: SmartConfiguration,
            *,
            state: str,
            code_challenge: str,
        ) -> str:
            observed["authorization"] = (discovered, state, code_challenge)
            return "https://epic.example.test/authorize"

        async def exchange_code(self, discovered: SmartConfiguration, **kwargs: str) -> EpicToken:
            observed["exchange"] = kwargs
            return EpicToken(access_token="synthetic-access-token")

        async def search_patients(
            self,
            access_token: str,
            *,
            patient_id: str,
        ) -> EpicPatientSearchResult:
            observed["search"] = (access_token, patient_id)
            return EpicPatientSearchResult(
                total=1,
                patients=[
                    EpicPatient(
                        resourceType="Patient",
                        id="sample-001",
                        name=[EpicPatientName(given=["Alex"], family="Sample")],
                    )
                ],
            )

    class FakeTokenCache:
        def load(self) -> None:
            return None

        def save(self, token: EpicToken) -> None:
            observed["cached_token"] = token

        def clear(self) -> None:
            observed["cache_cleared"] = True

    monkeypatch.setattr(epic_cli.EpicConfig, "from_environment", lambda: config)
    monkeypatch.setattr(epic_cli, "EpicSmartClient", lambda settings: FakeEpicClient())
    monkeypatch.setattr(epic_cli, "EpicTokenCache", lambda settings: FakeTokenCache())
    monkeypatch.setattr(
        epic_cli,
        "_read_epic_callback",
        lambda authorization_url, redirect_uri: {
            "code": "synthetic-code",
            "state": "synthetic-state",
        },
    )
    console = Console(record=True, width=100)

    asyncio.run(epic_cli.list_epic_patients("sample-001", console))

    output = console.export_text()
    assert "sample-001" in output
    assert "Alex Sample" in output
    assert "synthetic-access-token" not in output
    assert observed["search"] == ("synthetic-access-token", "sample-001")
    assert observed["cached_token"].access_token == "synthetic-access-token"
    assert observed["exchange"] == {
        "code": "synthetic-code",
        "returned_state": "synthetic-state",
        "expected_state": "synthetic-state",
        "code_verifier": "synthetic-verifier",
    }


def test_patient_cli_reuses_unexpired_cached_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    from folium_agents.epic import epic_cli
    from folium_agents.epic.epic import (
        CachedEpicToken,
        EpicPatient,
        EpicPatientName,
        EpicPatientSearchResult,
    )

    config = _epic_config(
        client_id="sandbox-client",
        redirect_uri="http://localhost:8765/callback",
    )
    smart = SmartConfiguration(
        authorization_endpoint="https://epic.example.test/oauth/authorize",
        token_endpoint="https://epic.example.test/oauth/token",
        code_challenge_methods_supported=["S256"],
    )
    cached = CachedEpicToken(
        token=EpicToken(
            access_token="synthetic-cached-access-token",
            expires_in=600,
        ),
        expires_at=time.time() + 600,
    )
    observed: dict[str, object] = {}

    class FakeEpicClient:
        async def discover(self) -> SmartConfiguration:
            return smart

        async def search_patients(
            self,
            access_token: str,
            *,
            patient_id: str,
        ) -> EpicPatientSearchResult:
            observed["search"] = (access_token, patient_id)
            return EpicPatientSearchResult(
                total=1,
                patients=[
                    EpicPatient(
                        resourceType="Patient",
                        id=patient_id,
                        name=[EpicPatientName(given=["Alex"], family="Sample")],
                    )
                ],
            )

    class FakeTokenCache:
        def load(self) -> CachedEpicToken:
            return cached

        def save(self, token: EpicToken) -> None:
            pytest.fail("A valid cached token should not be rewritten.")

        def clear(self) -> None:
            pytest.fail("A valid cached token should not be cleared.")

    monkeypatch.setattr(epic_cli.EpicConfig, "from_environment", lambda: config)
    monkeypatch.setattr(epic_cli, "EpicSmartClient", lambda settings: FakeEpicClient())
    monkeypatch.setattr(epic_cli, "EpicTokenCache", lambda settings: FakeTokenCache())
    monkeypatch.setattr(
        epic_cli,
        "_authorize_epic",
        lambda *args: pytest.fail("A valid cached token should skip browser login."),
    )
    console = Console(record=True, width=100)

    asyncio.run(epic_cli.list_epic_patients("sample-001", console))

    assert observed["search"] == ("synthetic-cached-access-token", "sample-001")
    assert "Reusing the saved Epic access token." in console.export_text()


def test_top_level_cli_runs_epic_oauth_and_patient_search_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from urllib.parse import parse_qs

    from folium_agents.core import cli as harness_cli
    from folium_agents.epic import epic_cli

    config = _epic_config(
        client_id="synthetic-client",
        redirect_uri="http://localhost:8765/callback",
        issuer="https://epic.example.test/api/FHIR/R4",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/.well-known/smart-configuration"):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": "https://epic.example.test/oauth/authorize",
                    "token_endpoint": "https://epic.example.test/oauth/token",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if request.url.path == "/oauth/token":
            form = dict(parse_qs(request.content.decode()))
            assert form["grant_type"] == ["authorization_code"]
            assert form["client_id"] == ["synthetic-client"]
            assert form["code"] == ["synthetic-code"]
            assert form["code_verifier"] == ["synthetic-verifier"]
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access-token",
                    "expires_in": 600,
                },
            )
        if request.url.path.endswith("/Patient"):
            assert request.headers["Authorization"] == "Bearer synthetic-access-token"
            assert request.url.params["_id"] == "synthetic-patient-id"
            return httpx.Response(
                200,
                json={
                    "resourceType": "Bundle",
                    "total": 1,
                    "entry": [
                        {
                            "resource": {
                                "resourceType": "Patient",
                                "id": "synthetic-patient-id",
                                "name": [
                                    {
                                        "given": ["Test"],
                                        "family": "Patient",
                                    }
                                ],
                            }
                        }
                    ],
                },
            )
        pytest.fail(f"Unexpected API request: {request.method} {request.url}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api_client = EpicSmartClient(config, http_client=http_client)
    cached_tokens: list[EpicToken] = []

    class FakeTokenCache:
        def load(self) -> None:
            return None

        def save(self, token: EpicToken) -> None:
            cached_tokens.append(token)

        def clear(self) -> None:
            cached_tokens.clear()

    def callback(authorization_url: str, redirect_uri: str) -> dict[str, str]:
        query = parse_qs(urlparse(authorization_url).query)
        assert query["client_id"] == ["synthetic-client"]
        assert query["redirect_uri"] == [config.redirect_uri]
        assert query["code_challenge_method"] == ["S256"]
        return {
            "code": "synthetic-code",
            "state": query["state"][0],
        }

    monkeypatch.setattr(EpicConfig, "from_environment", lambda: config)
    monkeypatch.setattr(epic_cli, "EpicSmartClient", lambda settings: api_client)
    monkeypatch.setattr(epic_cli, "EpicTokenCache", lambda settings: FakeTokenCache())
    monkeypatch.setattr(epic_cli, "_read_epic_callback", callback)
    monkeypatch.setattr(
        api_client,
        "create_pkce_pair",
        lambda: ("synthetic-verifier", "synthetic-challenge"),
    )
    harness_cli.main(
        [
            "epic",
            "patients",
            "--patient-id",
            "synthetic-patient-id",
        ]
    )
    asyncio.run(http_client.aclose())

    output = capsys.readouterr().out
    assert "synthetic-patient-id" in output
    assert "Test Patient" in output
    assert "synthetic-access-token" not in output
    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    assert len(cached_tokens) == 1
    assert cached_tokens[0].access_token == "synthetic-access-token"
