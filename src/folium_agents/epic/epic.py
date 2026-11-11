"""SMART on FHIR client primitives for the Epic sandbox."""

import base64
import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt
import keyring
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EPIC_FHIR_ISSUER = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
DEFAULT_EPIC_SCOPE = "openid fhirUser user/Patient.rs"
TOKEN_KEYRING_SERVICE = "folium-agents-epic"
TOKEN_EXPIRY_SKEW_SECONDS = 30


class EpicConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EPIC_",
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    client_id: str
    redirect_uri: str
    client_secret: SecretStr | None = None
    token_auth_method: Literal[
        "none",
        "client_secret_post",
        "client_secret_basic",
        "private_key_jwt",
    ] = "none"
    private_key_path: Path | None = None
    private_key_id: str | None = None
    private_key_passphrase: SecretStr | None = None
    private_key_algorithm: Literal["RS384", "ES384"] = "RS384"
    scope: str = DEFAULT_EPIC_SCOPE
    issuer: str = DEFAULT_EPIC_FHIR_ISSUER

    @classmethod
    def from_environment(cls) -> "EpicConfig":
        return cls()


class SmartConfiguration(BaseModel):
    authorization_endpoint: str
    token_endpoint: str
    code_challenge_methods_supported: list[str] = Field(default_factory=list)


class CapabilitySearchParameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str | None = None


class CapabilityInteraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str


class CapabilityResource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: str = Field(alias="type")
    interactions: list[CapabilityInteraction] = Field(
        default_factory=list,
        alias="interaction",
    )
    search_parameters: list[CapabilitySearchParameter] = Field(
        default_factory=list,
        alias="searchParam",
    )


class CapabilityRest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resources: list[CapabilityResource] = Field(default_factory=list, alias="resource")


class FhirCapabilityStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["CapabilityStatement"] = Field(alias="resourceType")
    rest: list[CapabilityRest] = Field(default_factory=list)


class EpicToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None
    patient: str | None = None
    encounter: str | None = None


class CachedEpicToken(BaseModel):
    token: EpicToken
    expires_at: float

    @property
    def is_valid(self) -> bool:
        return self.expires_at > time.time() + TOKEN_EXPIRY_SKEW_SECONDS


class EpicTokenCache:
    def __init__(self, config: EpicConfig) -> None:
        self._account = hashlib.sha256(
            f"{config.client_id}|{config.redirect_uri}|{config.issuer}".encode()
        ).hexdigest()

    def load(self) -> CachedEpicToken | None:
        value = keyring.get_password(TOKEN_KEYRING_SERVICE, self._account)
        if value is None:
            return None
        try:
            return CachedEpicToken.model_validate_json(value)
        except ValueError:
            self.clear()
            raise ValueError(
                "The saved Epic token entry is invalid and has been removed. "
                "Run the command again to authorize."
            ) from None

    def save(self, token: EpicToken) -> None:
        if token.expires_in is None or token.expires_in <= 0:
            self.clear()
            return
        cached = CachedEpicToken(
            token=token,
            expires_at=time.time() + token.expires_in,
        )
        keyring.set_password(
            TOKEN_KEYRING_SERVICE,
            self._account,
            cached.model_dump_json(),
        )

    def clear(self) -> None:
        if keyring.get_password(TOKEN_KEYRING_SERVICE, self._account) is not None:
            keyring.delete_password(TOKEN_KEYRING_SERVICE, self._account)


class CarePlanSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["CarePlan"] = Field(alias="resourceType")
    id: str
    status: str | None = None
    subject: dict[str, Any] | None = None
    encounter: dict[str, Any] | None = None


class EpicPatientName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    family: str = ""
    given: list[str] = Field(default_factory=list)


class EpicPatient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Patient"] = Field(alias="resourceType")
    id: str
    name: list["EpicPatientName"] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        for patient_name in self.name:
            parts = [*patient_name.given, patient_name.family]
            display_name = " ".join(part for part in parts if part)
            if display_name:
                return display_name
        return "(name unavailable)"


class PatientBundleEntry(BaseModel):
    resource: EpicPatient


class EpicPatientSearchResult(BaseModel):
    total: int | None = None
    patients: list[EpicPatient]


class EpicPatientBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Bundle"] = Field(alias="resourceType")
    total: int | None = None
    entry: list[PatientBundleEntry] = Field(default_factory=list)


class EpicSmartClient:
    def __init__(
        self,
        config: EpicConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client

    @staticmethod
    def create_pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    @staticmethod
    def create_state() -> str:
        return secrets.token_urlsafe(32)

    async def discover(self, issuer: str | None = None) -> SmartConfiguration:
        fhir_issuer = (issuer or self._config.issuer).rstrip("/")
        response = await self._request(
            "GET",
            f"{fhir_issuer}/.well-known/smart-configuration",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return SmartConfiguration.model_validate(response.json())

    async def discover_fhir_capabilities(
        self,
        issuer: str | None = None,
    ) -> FhirCapabilityStatement:
        fhir_issuer = (issuer or self._config.issuer).rstrip("/")
        response = await self._request(
            "GET",
            f"{fhir_issuer}/metadata",
            headers={"Accept": "application/fhir+json"},
        )
        response.raise_for_status()
        return FhirCapabilityStatement.model_validate(response.json())

    def build_authorization_url(
        self,
        smart: SmartConfiguration,
        *,
        state: str,
        code_challenge: str,
        issuer: str | None = None,
        launch: str | None = None,
    ) -> str:
        if "S256" not in smart.code_challenge_methods_supported:
            raise ValueError("Epic SMART endpoint does not advertise PKCE S256.")
        if not state or not code_challenge:
            raise ValueError("OAuth state and PKCE code challenge are required.")

        fhir_issuer = issuer or self._config.issuer
        params = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "scope": self._config.scope,
            "state": state,
            "aud": fhir_issuer,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if launch:
            params["launch"] = launch
        return f"{smart.authorization_endpoint}?{urlencode(params)}"

    async def exchange_code(
        self,
        smart: SmartConfiguration,
        *,
        code: str,
        returned_state: str,
        expected_state: str,
        code_verifier: str,
    ) -> EpicToken:
        if not hmac.compare_digest(returned_state, expected_state):
            raise ValueError("OAuth state mismatch; refusing token exchange.")
        if not code or not code_verifier:
            raise ValueError("Authorization code and PKCE verifier are required.")

        form_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "code_verifier": code_verifier,
        }
        headers = {"Accept": "application/json"}
        self._add_client_auth(form_data, headers, smart.token_endpoint)

        response = await self._request(
            "POST",
            smart.token_endpoint,
            data=form_data,
            headers=headers,
        )
        response.raise_for_status()
        return EpicToken.model_validate(response.json())

    async def refresh_access_token(
        self,
        smart: SmartConfiguration,
        refresh_token: str,
    ) -> EpicToken:
        if not refresh_token:
            raise ValueError("A refresh token is required.")

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._config.client_id,
        }
        headers = {"Accept": "application/json"}
        self._add_client_auth(form_data, headers, smart.token_endpoint)

        response = await self._request(
            "POST",
            smart.token_endpoint,
            data=form_data,
            headers=headers,
        )
        response.raise_for_status()
        token = EpicToken.model_validate(response.json())
        if not token.refresh_token:
            token.refresh_token = refresh_token
        return token

    def _add_client_auth(
        self,
        form_data: dict[str, str],
        headers: dict[str, str],
        token_endpoint: str,
    ) -> None:
        auth_method = self._config.token_auth_method
        if auth_method == "client_secret_post":
            if not self._config.client_secret:
                raise ValueError("EPIC_CLIENT_SECRET is required for this client.")
            form_data["client_secret"] = self._config.client_secret.get_secret_value()
        elif auth_method == "client_secret_basic":
            if not self._config.client_secret:
                raise ValueError("EPIC_CLIENT_SECRET is required for this client.")
            credentials = (
                f"{self._config.client_id}:"
                f"{self._config.client_secret.get_secret_value()}"
            )
            encoded = base64.b64encode(credentials.encode()).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        elif auth_method == "private_key_jwt":
            assertion = self._create_client_assertion(token_endpoint)
            form_data["client_assertion_type"] = (
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            )
            form_data["client_assertion"] = assertion

    def _create_client_assertion(self, token_endpoint: str) -> str:
        config = self._config
        if config.private_key_path is None:
            raise ValueError("EPIC_PRIVATE_KEY_PATH is required for private_key_jwt.")
        if not config.private_key_path.is_file():
            raise ValueError("The configured Epic private-key file does not exist.")

        private_key_bytes = config.private_key_path.read_bytes()
        passphrase = (
            config.private_key_passphrase.get_secret_value().encode()
            if config.private_key_passphrase
            else None
        )
        private_key = load_pem_private_key(private_key_bytes, password=passphrase)
        now = int(time.time())
        claims = {
            "iss": config.client_id,
            "sub": config.client_id,
            "aud": token_endpoint,
            "iat": now,
            "exp": now + 300,
            "jti": secrets.token_urlsafe(24),
        }
        headers = {"typ": "JWT"}
        if config.private_key_id:
            headers["kid"] = config.private_key_id
        return jwt.encode(
            claims,
            private_key,
            algorithm=config.private_key_algorithm,
            headers=headers,
        )

    async def search_patients(
        self,
        access_token: str,
        *,
        patient_id: str,
        issuer: str | None = None,
    ) -> EpicPatientSearchResult:
        if not access_token:
            raise ValueError("An access token is required.")
        patient_id = patient_id.strip()
        if not patient_id:
            raise ValueError("A Patient FHIR ID is required.")

        base_url = (issuer or self._config.issuer).rstrip("/")
        response = await self._request(
            "GET",
            f"{base_url}/Patient",
            params={"_id": patient_id},
            headers={
                "Accept": "application/fhir+json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            details = self._operation_outcome_details(response)
            if details is None:
                raise
            raise httpx.HTTPStatusError(
                f"{error}. Epic OperationOutcome: {details}",
                request=error.request,
                response=response,
            ) from error
        bundle = EpicPatientBundle.model_validate(response.json())
        return EpicPatientSearchResult(
            total=bundle.total,
            patients=[entry.resource for entry in bundle.entry],
        )

    @staticmethod
    def _operation_outcome_details(response: httpx.Response) -> str | None:
        try:
            outcome = response.json()
        except ValueError:
            return None
        if not isinstance(outcome, dict) or outcome.get("resourceType") != "OperationOutcome":
            return None

        issues = outcome.get("issue")
        if not isinstance(issues, list):
            return None

        messages: list[str] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            details = issue.get("details")
            text = details.get("text") if isinstance(details, dict) else None
            diagnostics = issue.get("diagnostics")
            if isinstance(text, str) and text.strip():
                messages.append(text.strip())
            if isinstance(diagnostics, str) and diagnostics.strip():
                messages.append(diagnostics.strip())

        if not messages:
            return None
        return " ".join(dict.fromkeys(messages))[:500]

    async def get_care_plan(
        self,
        access_token: str,
        care_plan_id: str,
        *,
        issuer: str | None = None,
    ) -> CarePlanSummary:
        if not access_token or not care_plan_id:
            raise ValueError("Access token and CarePlan ID are required.")
        base_url = (issuer or self._config.issuer).rstrip("/")
        response = await self._request(
            "GET",
            f"{base_url}/CarePlan/{care_plan_id}",
            params={"_elements": "id,status,subject,encounter"},
            headers={
                "Accept": "application/fhir+json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        response.raise_for_status()
        return CarePlanSummary.model_validate(response.json())

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, url, **kwargs)

        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.request(method, url, **kwargs)
