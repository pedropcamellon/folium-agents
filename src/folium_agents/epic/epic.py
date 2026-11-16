"""SMART on FHIR client primitives for the Epic sandbox."""

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt
import keyring
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from folium_agents.epic.models import (
    CachedEpicToken,
    CarePlanSummary,
    ClinicalRecordSummary,
    EpicMedicationSafetyReview,
    EpicPatient,
    EpicPatientBundle,
    EpicPatientSearchResult,
    EpicToken,
    FhirCapabilityStatement,
    FhirClinicalRecord,
    FhirMedicationRequest,
    FhirOperationOutcome,
    FhirResourceSearchResult,
    FhirSearchBundle,
    MedicationEntrySummary,
    PossibleDuplicateMedication,
    SmartConfiguration,
)

DEFAULT_EPIC_FHIR_ISSUER = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
DEFAULT_EPIC_SCOPE = "openid fhirUser user/Patient.rs"
MEDICATION_REVIEW_SCOPE = (
    "openid fhirUser launch/patient patient/MedicationRequest.rs "
    "patient/AllergyIntolerance.rs patient/Condition.rs patient/Patient.r "
    "user/ExplanationOfBenefit.rs"
)
TOKEN_KEYRING_SERVICE = "folium-agents-epic"


class EpicPatientSearchRejected(ValueError):
    """Epic returned a FHIR outcome instead of usable patient candidates."""

    def __init__(
        self,
        message: str,
        *,
        provider_issue_codes: tuple[str, ...] = (),
        provider_issue_severities: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.provider_issue_codes = provider_issue_codes
        self.provider_issue_severities = provider_issue_severities


class EpicPatientSearchNoResults(EpicPatientSearchRejected):
    """Epic returned a not-found outcome for an otherwise valid search."""


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
    token_cache_enabled: bool = True

    @classmethod
    def from_environment(cls) -> "EpicConfig":
        return cls()


class EpicTokenCache:
    def __init__(
        self,
        config: EpicConfig,
        *,
        context_id: str | None = None,
    ) -> None:
        self._enabled = config.token_cache_enabled
        identity = f"{config.client_id}|{config.redirect_uri}|{config.issuer}"
        if context_id is not None:
            identity = f"{identity}|{config.scope}|{context_id}"
        self._account = hashlib.sha256(identity.encode()).hexdigest()

    def load(self) -> CachedEpicToken | None:
        if not self._enabled:
            return None
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
        if not self._enabled:
            return
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
        if not self._enabled:
            return
        if keyring.get_password(TOKEN_KEYRING_SERVICE, self._account) is not None:
            keyring.delete_password(TOKEN_KEYRING_SERVICE, self._account)


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
        if not isinstance(private_key, (RSAPrivateKey, EllipticCurvePrivateKey)):
            raise TypeError("Epic client assertions require an RSA or EC private key.")
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
        patient_id: str | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        birthdate: str | None = None,
        issuer: str | None = None,
    ) -> EpicPatientSearchResult:
        if not access_token:
            raise ValueError("An access token is required.")
        given_name = given_name.strip() if given_name else None
        family_name = family_name.strip() if family_name else None
        birthdate = birthdate.strip() if birthdate else None
        patient_id = patient_id.strip() if patient_id else None
        demographics = (given_name, family_name, birthdate)
        if patient_id and any(demographics):
            raise ValueError("Use either a Patient FHIR ID or demographic search.")
        if not patient_id and not all((given_name, family_name, birthdate)):
            raise ValueError(
                "Provide a given name, family name, and date of birth."
            )
        if given_name and len(given_name) > 200:
            raise ValueError("Patient given name must not exceed 200 characters.")
        if family_name and len(family_name) > 200:
            raise ValueError("Patient family name must not exceed 200 characters.")
        if patient_id and re.fullmatch(r"[A-Za-z0-9.-]{1,64}", patient_id) is None:
            raise ValueError("A valid Patient FHIR ID is required.")
        if birthdate:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", birthdate) is None:
                raise ValueError("Date of birth must use YYYY-MM-DD format.")
            try:
                date.fromisoformat(birthdate)
            except ValueError:
                raise ValueError("Date of birth must be a valid calendar date.") from None

        base_url = (issuer or self._config.issuer).rstrip("/")
        params = {"_count": "100"} if not patient_id else {"_id": patient_id}
        if given_name:
            params["given"] = given_name
        if family_name:
            params["family"] = family_name
        if birthdate:
            params["birthdate"] = birthdate
        response = await self._request(
            "GET",
            f"{base_url}/Patient",
            params=params,
            headers={
                "Accept": "application/fhir+json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        self._raise_for_status_with_operation_outcome(response)
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Epic returned a non-JSON Patient search response.") from None
        if isinstance(payload, dict) and payload.get("resourceType") == "OperationOutcome":
            try:
                outcome = FhirOperationOutcome.model_validate(payload)
            except ValidationError:
                raise ValueError("Epic returned an invalid Patient search outcome.") from None
            if self._is_patient_search_no_results(outcome):
                raise self._patient_search_no_results(outcome)
            if any(
                issue.severity in {"fatal", "error", "warning"}
                for issue in outcome.issue
            ):
                raise self._patient_search_outcome_rejection(outcome)
            raise ValueError("Epic returned no usable Patient search results.")
        try:
            bundle = EpicPatientBundle.model_validate(payload)
        except ValidationError:
            raise ValueError("Epic returned an invalid Patient search response.") from None
        if bundle.bundle_type != "searchset":
            raise ValueError("Epic returned a non-search Patient bundle.")
        patients = []
        for entry in bundle.entry:
            if entry.resource.get("resourceType") == "OperationOutcome":
                try:
                    outcome = FhirOperationOutcome.model_validate(entry.resource)
                except ValidationError:
                    raise ValueError(
                        "Epic returned an invalid Patient search outcome."
                    ) from None
                if (
                    self._is_patient_search_no_results(outcome)
                    and bundle.total in (None, 0)
                    and all(
                        item.resource.get("resourceType") == "OperationOutcome"
                        for item in bundle.entry
                    )
                ):
                    raise self._patient_search_no_results(outcome)
                if any(
                    issue.severity in {"fatal", "error", "warning"}
                    for issue in outcome.issue
                ):
                    raise self._patient_search_outcome_rejection(outcome)
                raise ValueError("Epic returned no usable Patient search results.")
            try:
                patients.append(EpicPatient.model_validate(entry.resource))
            except ValidationError:
                raise ValueError(
                    "Epic returned an invalid Patient search response."
                ) from None
        patient_ids = [patient.id for patient in patients]
        if (
            len(patient_ids) != len(set(patient_ids))
            or any(
                re.fullmatch(r"[A-Za-z0-9.-]{1,64}", patient_id) is None
                for patient_id in patient_ids
            )
        ):
            raise ValueError("Epic returned invalid or duplicate Patient search results.")
        if bundle.total is not None and bundle.total < len(patients):
            raise ValueError("Epic returned a contradictory Patient search total.")
        more_matches_available = any(
            link.relation == "next" for link in bundle.link
        ) or (bundle.total is not None and bundle.total > len(patients))
        return EpicPatientSearchResult(
            total=bundle.total,
            patients=patients,
            more_matches_available=more_matches_available,
        )

    @staticmethod
    def _patient_search_outcome_rejection(
        outcome: FhirOperationOutcome,
    ) -> EpicPatientSearchRejected:
        rejecting_issues = tuple(
            issue
            for issue in outcome.issue
            if issue.severity in {"fatal", "error", "warning"}
        )
        return EpicPatientSearchRejected(
            "Epic could not return patient candidates. Check your "
            "organization's minimum demographics and Patient.Search "
            "support or configuration.",
            provider_issue_codes=tuple(issue.code for issue in rejecting_issues),
            provider_issue_severities=tuple(
                issue.severity for issue in rejecting_issues
            ),
        )

    @staticmethod
    def _is_patient_search_no_results(outcome: FhirOperationOutcome) -> bool:
        return bool(outcome.issue) and (
            all(issue.code == "not-found" for issue in outcome.issue)
            or all(
                issue.code == "processing" and issue.severity == "warning"
                for issue in outcome.issue
            )
        )

    @staticmethod
    def _patient_search_no_results(
        outcome: FhirOperationOutcome,
    ) -> EpicPatientSearchNoResults:
        return EpicPatientSearchNoResults(
            "Epic returned no matching Patient candidates.",
            provider_issue_codes=tuple(issue.code for issue in outcome.issue),
            provider_issue_severities=tuple(
                issue.severity for issue in outcome.issue
            ),
        )

    async def get_patient(
        self,
        access_token: str,
        patient_id: str,
        *,
        issuer: str | None = None,
    ) -> EpicPatient:
        if not access_token:
            raise ValueError("An access token is required.")
        if (
            not patient_id
            or patient_id in {".", ".."}
            or re.fullmatch(r"[A-Za-z0-9.-]{1,64}", patient_id) is None
        ):
            raise ValueError("A valid Patient FHIR ID is required.")

        base_url = (issuer or self._config.issuer).rstrip("/")
        response = await self._request(
            "GET",
            f"{base_url}/Patient/{patient_id}",
            headers={
                "Accept": "application/fhir+json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        self._raise_for_status_with_operation_outcome(response)
        try:
            patient = EpicPatient.model_validate(response.json())
        except ValidationError:
            raise ValueError("Epic did not return a valid FHIR Patient.") from None
        if patient.id != patient_id:
            raise ValueError("Epic returned a Patient outside the selected context.")
        return patient

    async def review_medications(
        self,
        access_token: str,
        *,
        patient_id: str,
        issuer: str | None = None,
    ) -> EpicMedicationSafetyReview:
        patient_id = patient_id.strip()
        if not access_token or not patient_id:
            raise ValueError("An access token and Patient FHIR ID are required.")

        medication_search, allergy_search, condition_search = await asyncio.gather(
            self._search_patient_resource(
                access_token,
                "MedicationRequest",
                patient_id,
                issuer=issuer,
                extra_params={"status": "active"},
            ),
            self._search_patient_resource(
                access_token,
                "AllergyIntolerance",
                patient_id,
                issuer=issuer,
            ),
            self._search_patient_resource(
                access_token,
                "Condition",
                patient_id,
                issuer=issuer,
            ),
        )

        try:
            medication_requests = [
                FhirMedicationRequest.model_validate(resource)
                for resource in medication_search.resources
            ]
        except ValidationError as error:
            details = self._validation_error_summary(error)
            shapes = self._resource_shape_summary(medication_search.resources)
            raise ValueError(
                "Epic MedicationRequest results did not match the expected FHIR "
                f"shape: {details}; received resource shapes: {shapes}"
            ) from None
        try:
            allergies = [
                FhirClinicalRecord.model_validate(resource)
                for resource in allergy_search.resources
            ]
            conditions = [
                FhirClinicalRecord.model_validate(resource)
                for resource in condition_search.resources
            ]
        except ValidationError as error:
            details = self._validation_error_summary(error)
            raise ValueError(
                "Epic allergy or condition results did not match the expected FHIR "
                f"shape: {details}"
            ) from None

        active_requests = [
            request for request in medication_requests if request.status == "active"
        ]
        medication_summaries: list[MedicationEntrySummary] = []
        requests_by_code: dict[tuple[str, str], list[FhirMedicationRequest]] = {}
        for request in active_requests:
            medication_summaries.append(
                MedicationEntrySummary(
                    resource_id=request.id,
                    display=request.medication_display,
                    status=request.status,
                    authored_on=request.authored_on,
                    dosage_text=request.dosage_text,
                    code_system=request.medication_code[0]
                    if request.medication_code
                    else None,
                    code=request.medication_code[1]
                    if request.medication_code
                    else None,
                )
            )
            if request.medication_code:
                requests_by_code.setdefault(request.medication_code, []).append(request)

        duplicate_medications = [
            PossibleDuplicateMedication(
                display=requests[0].medication_display,
                code_system=code_system,
                code=code,
                resource_ids=[request.id for request in requests],
            )
            for (code_system, code), requests in requests_by_code.items()
            if len(requests) > 1
        ]
        return EpicMedicationSafetyReview(
            patient_id=patient_id,
            active_medications=medication_summaries,
            allergies=[self._clinical_record_summary(record) for record in allergies],
            conditions=[self._clinical_record_summary(record) for record in conditions],
            possible_duplicate_medications=duplicate_medications,
            outcome_notes=[
                *medication_search.outcome_notes,
                *allergy_search.outcome_notes,
                *condition_search.outcome_notes,
            ],
        )

    async def _search_patient_resource(
        self,
        access_token: str,
        resource_type: Literal[
            "MedicationRequest",
            "AllergyIntolerance",
            "Condition",
        ],
        patient_id: str,
        *,
        issuer: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> FhirResourceSearchResult:
        base_url = (issuer or self._config.issuer).rstrip("/")
        params = {"patient": patient_id, "_count": "100"}
        if extra_params:
            params.update(extra_params)
        response = await self._request(
            "GET",
            f"{base_url}/{resource_type}",
            params=params,
            headers={
                "Accept": "application/fhir+json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        self._raise_for_status_with_operation_outcome(response)
        try:
            bundle = FhirSearchBundle.model_validate(response.json())
        except ValidationError:
            raise ValueError(
                f"Epic {resource_type} search did not return a valid FHIR Bundle."
            ) from None
        if bundle.bundle_type != "searchset":
            raise ValueError(
                f"Epic {resource_type} search did not return a searchset Bundle."
            )
        resources: list[dict[str, Any]] = []
        outcome_notes: list[str] = []
        for entry in bundle.entry:
            resource = entry.resource
            if resource.get("resourceType") != "OperationOutcome":
                resources.append(resource)
                continue
            try:
                outcome = FhirOperationOutcome.model_validate(resource)
            except ValidationError as error:
                details = self._validation_error_summary(error)
                raise ValueError(
                    f"Epic {resource_type} search returned an invalid "
                    f"OperationOutcome: {details}"
                ) from None
            for issue in outcome.issue:
                note = f"{resource_type} outcome {issue.severity}/{issue.code}"
                if issue.severity in {"fatal", "error"}:
                    raise ValueError(
                        f"Epic {resource_type} search returned {note}; "
                        "no medication review was produced."
                    )
                outcome_notes.append(note)

        if (
            any(link.relation == "next" for link in bundle.link)
            or bundle.total is not None
            and bundle.total > len(resources)
        ):
            raise ValueError(
                f"Epic {resource_type} search results are incomplete; "
                "no partial medication review was produced."
            )
        return FhirResourceSearchResult(
            resources=resources,
            outcome_notes=outcome_notes,
        )

    @staticmethod
    def _clinical_record_summary(
        record: FhirClinicalRecord,
    ) -> ClinicalRecordSummary:
        return ClinicalRecordSummary(
            resource_id=record.id,
            display=record.display,
            clinical_status=record.clinical_status_display,
            verification_status=record.verification_status_display,
            date=record.recorded_date or record.onset_date_time,
        )

    @staticmethod
    def _raise_for_status_with_operation_outcome(
        response: httpx.Response,
    ) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            details = EpicSmartClient._operation_outcome_details(response)
            if details is None:
                raise
            raise httpx.HTTPStatusError(
                f"{error}. Epic OperationOutcome: {details}",
                request=error.request,
                response=response,
            ) from error

    @staticmethod
    def _validation_error_summary(error: ValidationError) -> str:
        return "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors(
                include_input=False,
                include_context=False,
                include_url=False,
            )
        )

    @staticmethod
    def _resource_shape_summary(resources: list[dict[str, Any]]) -> str:
        summaries = []
        for index, resource in enumerate(resources[:3], start=1):
            resource_type = resource.get("resourceType")
            type_name = resource_type if isinstance(resource_type, str) else "missing"
            keys = sorted(key for key in resource if isinstance(key, str))
            summaries.append(
                f"entry {index}: resourceType={type_name!r}; keys={','.join(keys)}"
            )
        remaining = len(resources) - len(summaries)
        if remaining > 0:
            summaries.append(f"{remaining} additional entries")
        return "; ".join(summaries)

    @staticmethod
    def _operation_outcome_details(response: httpx.Response) -> str | None:
        try:
            outcome = response.json()
        except ValueError:
            return None
        if (
            not isinstance(outcome, dict)
            or outcome.get("resourceType") != "OperationOutcome"
        ):
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
