import asyncio
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from folium_agents.core.financial import (
    ClaimAmount,
    ClaimEvidence,
    ClaimSearch,
    ClaimSearchError,
)
from folium_agents.epic.epic import DEFAULT_EPIC_FHIR_ISSUER
from folium_agents.epic.models import FhirOperationOutcome

MAX_PAGES = 10
MAX_RECORDS = 1000


class FhirMoney(BaseModel):
    value: Decimal = Field(allow_inf_nan=False)
    currency: str | None = None


class FhirCoding(BaseModel):
    code: str


class FhirCategory(BaseModel):
    coding: list[FhirCoding] = Field(min_length=1)


class FhirTotal(BaseModel):
    category: FhirCategory
    amount: FhirMoney


class FhirReference(BaseModel):
    reference: str = Field(min_length=1)


class FhirClaim(BaseModel):
    resource_type: Literal["ExplanationOfBenefit"] = Field(alias="resourceType")
    use: Literal["claim"]
    id: str = Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")
    status: Literal["active", "cancelled", "draft", "entered-in-error"]
    created: str = Field(min_length=1)
    patient: FhirReference
    total: list[FhirTotal] = Field(default_factory=list)


class SearchEntry(BaseModel):
    resource: FhirClaim | FhirOperationOutcome = Field(discriminator="resource_type")


class SearchLink(BaseModel):
    relation: str
    url: str


class SearchBundle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resource_type: Literal["Bundle"] = Field(alias="resourceType")
    bundle_type: Literal["searchset"] = Field(alias="type")
    entry: list[SearchEntry] = Field(default_factory=list)
    link: list[SearchLink] = Field(default_factory=list)
    total: int | None = Field(default=None, ge=0)


class FinancialReadError(ClaimSearchError):
    pass


def validate_sandbox(issuer: str) -> None:
    if issuer.rstrip("/") != DEFAULT_EPIC_FHIR_ISSUER:
        raise FinancialReadError(
            "Financial reads are restricted to the public Epic sandbox."
        )


def validate_claim_search_scope(scope: str | None) -> None:
    if scope is None:
        return
    granted = set(scope.split())
    supported_grants = (
        {"user/ExplanationOfBenefit.rs"},
        {"user/ExplanationOfBenefit.r", "user/ExplanationOfBenefit.s"},
        {"user/ExplanationOfBenefit.read"},
    )
    if not any(grant <= granted for grant in supported_grants):
        raise FinancialReadError(
            "Epic authorization is missing ExplanationOfBenefit read and search "
            "permissions. Enable both for this app, then reauthorize the patient."
        )


def validate_patient_id(patient_id: str) -> None:
    if (
        not patient_id
        or len(patient_id) > 64
        or not all(
            character.isascii() and (character.isalnum() or character in ".-")
            for character in patient_id
        )
    ):
        raise FinancialReadError("Provide a valid Patient FHIR ID.")


def validate_patient_reference(reference: str, patient_id: str, issuer: str) -> None:
    parsed = urlsplit(reference)
    if parsed.query or parsed.fragment:
        raise FinancialReadError("Epic returned a malformed patient reference.")
    if parsed.netloc and (
        parsed.scheme != "https" or parsed.netloc != urlsplit(issuer).netloc
    ):
        raise FinancialReadError(
            "Epic returned a patient reference from an unexpected server."
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2:] != ["Patient", patient_id]:
        raise FinancialReadError(
            "Epic returned a claim for a different or unidentified patient."
        )


def next_page_url(base: str, current: str, link: str, patient_id: str) -> str:
    candidate = urljoin(current, link)
    expected = urlsplit(base)
    actual = urlsplit(candidate)
    if (
        actual.scheme != expected.scheme
        or actual.netloc != expected.netloc
        or actual.path not in {expected.path, f"{expected.path}/ExplanationOfBenefit"}
        or actual.fragment
        or (
            "patient" in parse_qs(actual.query, keep_blank_values=True)
            and parse_qs(actual.query, keep_blank_values=True)["patient"]
            != [patient_id]
        )
        or (
            "use" in parse_qs(actual.query, keep_blank_values=True)
            and parse_qs(actual.query, keep_blank_values=True)["use"] != ["claim"]
        )
    ):
        raise FinancialReadError(
            "Epic returned an unsafe, changed-patient, or non-claim pagination link."
        )
    return candidate


async def search_claims(
    *,
    issuer: str,
    access_token: str,
    patient_id: str,
    client: httpx.AsyncClient,
) -> ClaimSearch:
    validate_sandbox(issuer)
    validate_patient_id(patient_id)
    base = issuer.rstrip("/")
    url = f"{base}/ExplanationOfBenefit"
    params: dict[str, str] | None = {
        "patient": patient_id,
        "use": "claim",
        "_count": "100",
    }
    claims: dict[str, ClaimEvidence] = {}
    visited: set[str] = set()
    expected_total: int | None = None
    limitations = [
        "Search covers claims across all dates available for this patient through this grant, not prior authorizations or all organization claims.",
        "EOB adjudication and amounts do not establish internal payment-posting status.",
        "Results are limited to the explicitly selected Patient FHIR ID.",
        "A record or page limit stops the search with an error; incomplete results are never returned as complete.",
    ]
    async with asyncio.timeout(60):
        for page in range(1, MAX_PAGES + 1):
            response = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/fhir+json",
                },
                follow_redirects=False,
                timeout=15,
            )
            if response.status_code in {401, 403}:
                raise FinancialReadError(
                    f"Epic denied ExplanationOfBenefit search (HTTP {response.status_code}). "
                    "Confirm the app has read and search access, then reauthorize this patient."
                )
            if response.status_code == 400:
                raise FinancialReadError(
                    "Epic rejected the patient-filtered claim search (HTTP 400); no fallback was attempted."
                )
            if not response.is_success:
                raise FinancialReadError(
                    f"Epic claim search failed (HTTP {response.status_code}); no claims were accepted."
                )
            if len(response.content) > 2_000_000:
                raise FinancialReadError(
                    "Epic claim response exceeded the accepted size limit."
                )
            try:
                bundle = SearchBundle.model_validate_json(response.content)
            except ValidationError as error:
                raise FinancialReadError(
                    "Epic returned a malformed claim response; no claims were accepted."
                ) from error
            if bundle.total is not None:
                if expected_total is not None and bundle.total != expected_total:
                    raise FinancialReadError(
                        "Epic result count changed between pages; retry the search."
                    )
                expected_total = bundle.total
            for entry in bundle.entry:
                record = entry.resource
                if isinstance(record, FhirOperationOutcome):
                    if any(issue.code == "suppressed" for issue in record.issue):
                        raise FinancialReadError(
                            "Epic suppressed claim search results. Full patient claim "
                            "coverage cannot be verified; no claims were accepted. "
                            "Confirm access to this sandbox patient's financial records."
                        )
                    no_results = bool(record.issue) and all(
                        issue.severity == "warning"
                        and issue.code == "processing"
                        and issue.details is not None
                        and any(
                            coding.code == "4101"
                            for coding in issue.details.coding or []
                        )
                        for issue in record.issue
                    )
                    if (
                        no_results
                        and not claims
                        and not any(
                            isinstance(item.resource, FhirClaim)
                            for item in bundle.entry
                        )
                        and expected_total in {None, 0}
                        and not any(link.relation == "next" for link in bundle.link)
                    ):
                        limitations.append(
                            "Epic reported no matching claims for the selected patient."
                        )
                        continue
                    if not record.issue or any(
                        issue.severity in {"fatal", "error", "warning"}
                        for issue in record.issue
                    ):
                        raise FinancialReadError(
                            "Epic reported a claim search processing or access warning. "
                            "No claims were accepted; retry or confirm sandbox access."
                        )
                    limitations.append(
                        "Epic returned an informational claim search outcome."
                    )
                    continue
                validate_patient_reference(record.patient.reference, patient_id, base)
                try:
                    date.fromisoformat(record.created[:10])
                except ValueError as error:
                    raise FinancialReadError(
                        "Epic returned an invalid claim date; no claims were accepted."
                    ) from error
                if record.id in claims:
                    raise FinancialReadError(
                        "Epic returned duplicate claim IDs; coverage is ambiguous."
                    )
                claims[record.id] = ClaimEvidence(
                    claim_id=record.id,
                    status=record.status,
                    created=record.created,
                    source_id=f"ExplanationOfBenefit/{record.id}",
                    amounts=[
                        ClaimAmount(
                            category=total.category.coding[0].code,
                            value=str(total.amount.value),
                            currency=total.amount.currency,
                        )
                        for total in record.total
                    ],
                )
            if len(claims) > MAX_RECORDS:
                raise FinancialReadError(
                    "Epic claim search exceeded the accepted record limit."
                )
            visited.add(str(response.url))
            next_links = [link.url for link in bundle.link if link.relation == "next"]
            if len(next_links) > 1:
                raise FinancialReadError("Epic returned ambiguous pagination links.")
            if not next_links:
                if expected_total is not None and expected_total != len(claims):
                    raise FinancialReadError(
                        "Epic result count is inconsistent; coverage is incomplete."
                    )
                return ClaimSearch(
                    source="epic-sandbox",
                    patient_id=patient_id,
                    claims=list(claims.values()),
                    pages=page,
                    complete=True,
                    limitations=limitations,
                )
            url = next_page_url(base, str(response.url), next_links[0], patient_id)
            if url in visited:
                raise FinancialReadError(
                    "Epic pagination repeated a page; coverage is incomplete."
                )
            params = None
    raise FinancialReadError(
        "Epic claim search exceeded the page limit; narrow the date range."
    )
