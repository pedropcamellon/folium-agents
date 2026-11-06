import asyncio

import httpx
import pytest

from folium_agents.openemr import OpenEMRConfig, OpenEMRFhirClient


def test_get_capability_statement_uses_fhir_endpoint_and_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "resourceType": "CapabilityStatement",
                "fhirVersion": "4.0.1",
                "status": "active",
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fhir = OpenEMRFhirClient(
                OpenEMRConfig(
                    fhir_base_url="https://openemr.example/apis/default/fhir/",
                    access_token="test-token",
                ),
                http_client=client,
            )
            statement = await fhir.get_capability_statement()
            assert statement.resource_type == "CapabilityStatement"
            assert statement.fhir_version == "4.0.1"
            assert statement.status == "active"

    asyncio.run(run_test())
    assert len(requests) == 1
    assert str(requests[0].url) == "https://openemr.example/apis/default/fhir/metadata"
    assert requests[0].headers["Authorization"] == "Bearer test-token"


def test_get_capability_statement_surfaces_http_errors() -> None:
    async def run_test() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"error": "unauthorized"})
            )
        ) as client:
            fhir = OpenEMRFhirClient(
                OpenEMRConfig(fhir_base_url="https://openemr.example/fhir"),
                http_client=client,
            )
            with pytest.raises(httpx.HTTPStatusError):
                await fhir.get_capability_statement()

    asyncio.run(run_test())


def test_password_grant_then_patient_search_returns_ids_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"access_token": "synthetic-token", "token_type": "Bearer"},
            )
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "total": 2,
                "entry": [
                    {"resource": {"resourceType": "Patient", "id": "patient-1"}},
                    {"resource": {"resourceType": "Patient", "id": "patient-2"}},
                ],
            },
        )

    async def run_test() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fhir = OpenEMRFhirClient(
                OpenEMRConfig(
                    oauth_token_url="https://openemr.example/oauth2/default/token",
                    fhir_base_url="https://openemr.example/apis/default/fhir",
                    username="synthetic-user",
                    password="synthetic-password",
                    client_id="synthetic-client",
                    client_secret="synthetic-secret",
                ),
                http_client=client,
            )
            result = await fhir.list_patient_ids(limit=2)

        assert result.total == 2
        assert result.patient_ids == ["patient-1", "patient-2"]

    asyncio.run(run_test())
    assert len(requests) == 2
    assert requests[0].url == "https://openemr.example/oauth2/default/token"
    assert requests[0].headers["Content-Type"].startswith(
        "application/x-www-form-urlencoded"
    )
    assert requests[0].content.decode() == (
        "grant_type=password&client_id=synthetic-client&user_role=users"
        "&username=synthetic-user&password=synthetic-password"
        "&scope=openid+api%3Afhir+user%2FPatient.read"
        "&client_secret=synthetic-secret"
    )
    assert str(requests[1].url) == (
        "https://openemr.example/apis/default/fhir/Patient"
        "?_count=2&_elements=id"
    )
    assert requests[1].headers["Authorization"] == "Bearer synthetic-token"


def test_patient_search_requires_authentication_configuration() -> None:
    async def run_test() -> None:
        fhir = OpenEMRFhirClient(OpenEMRConfig())
        with pytest.raises(ValueError, match="OPENEMR_USERNAME"):
            await fhir.list_patient_ids()

    asyncio.run(run_test())


def test_patient_search_rejects_unbounded_page_size() -> None:
    async def run_test() -> None:
        fhir = OpenEMRFhirClient(OpenEMRConfig(access_token="synthetic-token"))
        with pytest.raises(ValueError, match="limit must be between"):
            await fhir.list_patient_ids(limit=101)

    asyncio.run(run_test())
