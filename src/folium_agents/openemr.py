"""Read-only FHIR client for OpenEMR."""

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_FHIR_BASE_URL = "https://demo.openemr.io/openemr/apis/default/fhir"
DEFAULT_OAUTH_TOKEN_URL = "https://demo.openemr.io/openemr/oauth2/default/token"
DEFAULT_PATIENT_SCOPE = "openid api:fhir user/Patient.read"
MAX_PATIENT_PAGE_SIZE = 100


@dataclass(frozen=True)
class OpenEMRConfig:
    fhir_base_url: str = DEFAULT_FHIR_BASE_URL
    oauth_token_url: str = DEFAULT_OAUTH_TOKEN_URL
    access_token: str | None = None
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    mfa_token: str | None = None
    scope: str = DEFAULT_PATIENT_SCOPE

    @classmethod
    def from_environment(cls) -> "OpenEMRConfig":
        return cls(
            fhir_base_url=os.getenv("OPENEMR_FHIR_BASE_URL", DEFAULT_FHIR_BASE_URL),
            oauth_token_url=os.getenv(
                "OPENEMR_OAUTH_TOKEN_URL",
                DEFAULT_OAUTH_TOKEN_URL,
            ),
            access_token=os.getenv("OPENEMR_ACCESS_TOKEN"),
            username=os.getenv("OPENEMR_USERNAME"),
            password=os.getenv("OPENEMR_PASSWORD"),
            client_id=os.getenv("OPENEMR_CLIENT_ID"),
            client_secret=os.getenv("OPENEMR_CLIENT_SECRET"),
            mfa_token=os.getenv("OPENEMR_MFA_TOKEN"),
            scope=os.getenv("OPENEMR_FHIR_SCOPE", DEFAULT_PATIENT_SCOPE),
        )


class CapabilityStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: str = Field(alias="resourceType")
    fhir_version: str = Field(alias="fhirVersion")
    status: str


class OAuthToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None


class FhirPatient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Patient"] = Field(alias="resourceType")
    id: str


class FhirBundleEntry(BaseModel):
    resource: FhirPatient


class PatientBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Bundle"] = Field(alias="resourceType")
    total: int | None = None
    entry: list[FhirBundleEntry] = Field(default_factory=list)


class PatientSearchResult(BaseModel):
    total: int | None
    patient_ids: list[str]


class OpenEMRFhirClient:
    def __init__(
        self,
        config: OpenEMRConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._base_url = config.fhir_base_url.rstrip("/")
        self._http_client = http_client
        self._access_token = config.access_token

    async def get_capability_statement(self) -> CapabilityStatement:
        response = await self._request(
            "GET",
            f"{self._base_url}/metadata",
            headers=self._authorization_headers(),
        )
        response.raise_for_status()
        return CapabilityStatement.model_validate(response.json())

    async def authenticate(self) -> OAuthToken:
        if self._access_token:
            return OAuthToken(access_token=self._access_token)

        config = self._config
        if not config.username or not config.password or not config.client_id:
            raise ValueError(
                "Set OPENEMR_USERNAME, OPENEMR_PASSWORD, and OPENEMR_CLIENT_ID "
                "or provide OPENEMR_ACCESS_TOKEN."
            )

        form_data = {
            "grant_type": "password",
            "client_id": config.client_id,
            "user_role": "users",
            "username": config.username,
            "password": config.password,
            "scope": config.scope,
        }
        if config.client_secret:
            form_data["client_secret"] = config.client_secret
        if config.mfa_token:
            form_data["mfa_token"] = config.mfa_token

        response = await self._request(
            "POST",
            config.oauth_token_url,
            data=form_data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        token = OAuthToken.model_validate(response.json())
        self._access_token = token.access_token
        return token

    async def list_patient_ids(self, *, limit: int = 20) -> PatientSearchResult:
        if not 1 <= limit <= MAX_PATIENT_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PATIENT_PAGE_SIZE}.")

        token = await self.authenticate()
        response = await self._request(
            "GET",
            f"{self._base_url}/Patient",
            params={"_count": limit, "_elements": "id"},
            headers=self._authorization_headers(token.access_token),
        )
        response.raise_for_status()
        bundle = PatientBundle.model_validate(response.json())
        return PatientSearchResult(
            total=bundle.total,
            patient_ids=[entry.resource.id for entry in bundle.entry],
        )

    def _authorization_headers(self, access_token: str | None = None) -> dict[str, str]:
        token = access_token or self._access_token
        headers = {"Accept": "application/fhir+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, url, **kwargs)

        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.request(method, url, **kwargs)
