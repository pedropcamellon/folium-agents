"""Epic sandbox command workflows."""

import asyncio
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse

import httpx
from rich.console import Console
from rich.table import Table

from folium_agents.epic.epic import (
    MEDICATION_REVIEW_SCOPE,
    EpicConfig,
    EpicSmartClient,
    EpicTokenCache,
)
from folium_agents.epic.models import (
    EpicMedicationSafetyReview,
    EpicToken,
    SmartConfiguration,
)


def _read_epic_callback(authorization_url: str, redirect_uri: str) -> dict[str, str]:
    redirect = urlparse(redirect_uri)
    if (
        redirect.scheme != "http"
        or redirect.hostname not in {"localhost", "127.0.0.1"}
        or redirect.port is None
        or redirect.username is not None
        or redirect.password is not None
        or redirect.fragment
    ):
        raise ValueError(
            "The local callback must be an http://localhost:<port>/<path> URI."
        )

    callback_received = Event()
    callback_params: dict[str, str] = {}
    expected_path = redirect.path or "/"

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request_url = urlparse(self.path)
            if request_url.path != expected_path:
                self.send_error(404)
                return

            callback_params.update(
                {key: values[0] for key, values in parse_qs(request_url.query).items()}
            )
            body = b"Epic authorization response received. Return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            callback_received.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", redirect.port), CallbackHandler)
    server.timeout = 300
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opened = webbrowser.open(authorization_url)
        if not opened:
            print(f"Open this URL to authorize: {authorization_url}")
        if not callback_received.wait(timeout=300):
            raise TimeoutError("Timed out waiting for Epic's OAuth callback.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return callback_params


async def discover_epic(console: Console) -> None:
    config = EpicConfig.from_environment()
    client = EpicSmartClient(config)
    smart = await client.discover()
    capabilities = await client.discover_fhir_capabilities()
    console.print(f"Authorization endpoint: {smart.authorization_endpoint}")
    console.print(f"Token endpoint: {smart.token_endpoint}")
    console.print(
        "PKCE S256: "
        f"{'supported' if 'S256' in smart.code_challenge_methods_supported else 'not supported'}"
    )
    console.print(f"FHIR metadata endpoint: {config.issuer.rstrip('/')}/metadata")

    resources = [resource for rest in capabilities.rest for resource in rest.resources]
    console.print(
        "FHIR server capabilities (these are not app-specific authorization grants):"
    )
    table = Table(title="FHIR resource interactions")
    table.add_column("Resource")
    table.add_column("Interactions")
    for resource in resources:
        table.add_row(
            resource.resource_type,
            ", ".join(interaction.code for interaction in resource.interactions),
        )
    console.print(table)
    console.print(
        "Actual access is still limited by the Epic app registration and granted token scopes."
    )

    patient = next(
        (resource for resource in resources if resource.resource_type == "Patient"),
        None,
    )
    if patient:
        search_params = ", ".join(
            parameter.name for parameter in patient.search_parameters
        )
        console.print(f"Patient search parameters: {search_params}")


def logout_epic(console: Console) -> None:
    token_cache = EpicTokenCache(EpicConfig.from_environment())
    token_cache.clear()
    console.print("Removed the saved Epic token from the OS credential store.")


async def list_epic_patients(patient_id: str, console: Console) -> None:
    config = EpicConfig.from_environment()
    client = EpicSmartClient(config)
    smart = await client.discover()
    token_cache = EpicTokenCache(config)
    cached = token_cache.load()

    if cached and cached.is_valid:
        token = cached.token
        console.print("Reusing the saved Epic access token.")
    elif cached and cached.token.refresh_token:
        try:
            token = await client.refresh_access_token(
                smart,
                cached.token.refresh_token,
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {400, 401}:
                raise
            token_cache.clear()
            console.print(
                "The saved Epic refresh token was rejected. Starting a new login."
            )
            token = await _authorize_epic(client, smart, config)
        else:
            console.print("Refreshed the saved Epic access token.")
        token_cache.save(token)
    else:
        if cached:
            token_cache.clear()
        token = await _authorize_epic(client, smart, config)
        token_cache.save(token)

    result = await client.search_patients(
        token.access_token,
        patient_id=patient_id,
    )

    table = Table(
        title=f"Epic sandbox Patient search ({len(result.patients)} returned)"
    )
    table.add_column("Patient ID", style="cyan")
    table.add_column("Name")
    for patient in result.patients:
        table.add_row(patient.id, patient.display_name)
    console.print(table)


async def review_patient_medications(patient_id: str, console: Console) -> None:
    patient_id = patient_id.strip()
    if not patient_id:
        raise ValueError("A Patient FHIR ID is required.")

    config = EpicConfig.from_environment()
    review_config = config.model_copy(update={"scope": MEDICATION_REVIEW_SCOPE})
    client = EpicSmartClient(review_config)
    smart = await client.discover()
    token_cache = EpicTokenCache(review_config, context_id=patient_id)
    token = await _get_medication_review_token(
        client,
        smart,
        review_config,
        token_cache,
        patient_id,
        console,
    )
    review = await client.review_medications(
        token.access_token,
        patient_id=patient_id,
    )
    _display_medication_review(review, console)


async def _get_medication_review_token(
    client: EpicSmartClient,
    smart: SmartConfiguration,
    config: EpicConfig,
    token_cache: EpicTokenCache,
    patient_id: str,
    console: Console,
) -> EpicToken:
    cached = token_cache.load()
    if cached and cached.token.patient != patient_id:
        token_cache.clear()
        cached = None

    if cached and cached.is_valid and cached.token.patient == patient_id:
        console.print("Reusing the saved Epic token for the selected patient.")
        return cached.token

    if cached and cached.token.refresh_token:
        try:
            token = await client.refresh_access_token(
                smart,
                cached.token.refresh_token,
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {400, 401}:
                raise
            token_cache.clear()
            console.print(
                "The saved Epic refresh token was rejected. Starting a new login."
            )
        else:
            if token.patient is None:
                token.patient = cached.token.patient
            if token.patient == patient_id:
                token_cache.save(token)
                console.print(
                    "Refreshed the saved Epic token for the selected patient."
                )
                return token
            token_cache.clear()

    token = await _authorize_epic(client, smart, config)
    if token.patient != patient_id:
        token_cache.clear()
        raise ValueError(
            "The authorized Epic patient context did not match the requested "
            "Patient FHIR ID; no chart data was accessed."
        )
    token_cache.save(token)
    return token


def _display_medication_review(
    review: EpicMedicationSafetyReview,
    console: Console,
) -> None:
    console.print(f"Read-only medication review for Patient {review.patient_id}")
    if review.outcome_notes:
        console.print("FHIR outcome notes (details withheld):")
        for note in review.outcome_notes:
            console.print(note)
        if any(" outcome warning/" in note for note in review.outcome_notes):
            console.print(
                "FHIR warnings may indicate omitted records; verify the full "
                "patient chart before relying on this review."
            )

    medications = Table(title="Active medication requests")
    medications.add_column("Resource ID")
    medications.add_column("Medication")
    medications.add_column("Status")
    medications.add_column("Authored")
    medications.add_column("Dosage text")
    medications.add_column("Code")
    for medication in review.active_medications:
        medications.add_row(
            medication.resource_id,
            medication.display,
            medication.status,
            medication.authored_on or "Not recorded",
            medication.dosage_text or "Not recorded",
            (
                f"{medication.code_system}|{medication.code}"
                if medication.code_system and medication.code
                else "No coded concept returned"
            ),
        )
    console.print(medications)
    if not review.active_medications:
        console.print(
            "No active MedicationRequest entries were returned; this does not "
            "prove that the patient takes no medications."
        )

    allergies = Table(title="Recorded allergies")
    allergies.add_column("Resource ID")
    allergies.add_column("Chart entry")
    allergies.add_column("Clinical status")
    allergies.add_column("Verification")
    allergies.add_column("Date")
    for allergy in review.allergies:
        allergies.add_row(
            allergy.resource_id,
            allergy.display,
            allergy.clinical_status,
            allergy.verification_status,
            allergy.date or "Not recorded",
        )
    console.print(allergies)
    if not review.allergies:
        console.print(
            "No AllergyIntolerance entries were returned; this does not prove "
            "the patient has no allergies."
        )

    conditions = Table(title="Recorded conditions")
    conditions.add_column("Resource ID")
    conditions.add_column("Chart entry")
    conditions.add_column("Clinical status")
    conditions.add_column("Verification")
    conditions.add_column("Date")
    for condition in review.conditions:
        conditions.add_row(
            condition.resource_id,
            condition.display,
            condition.clinical_status,
            condition.verification_status,
            condition.date or "Not recorded",
        )
    console.print(conditions)
    if not review.conditions:
        console.print(
            "No Condition entries were returned; this does not prove the patient "
            "has no relevant conditions."
        )

    duplicates = Table(title="Possible duplicate medication entries")
    duplicates.add_column("Medication")
    duplicates.add_column("Code")
    duplicates.add_column("Source resource IDs")
    for duplicate in review.possible_duplicate_medications:
        duplicates.add_row(
            duplicate.display,
            f"{duplicate.code_system}|{duplicate.code}",
            ", ".join(duplicate.resource_ids),
        )
    console.print(duplicates)
    if review.possible_duplicate_medications:
        console.print(
            "Possible duplicates are record-level flags only; verify them with a "
            "clinician. No interaction or treatment recommendation is generated."
        )
    else:
        console.print(
            "No exact-code duplicate active entries were detected. This does not "
            "establish that the medication regimen is safe."
        )


async def _authorize_epic(
    client: EpicSmartClient,
    smart: SmartConfiguration,
    config: EpicConfig,
) -> EpicToken:
    state = client.create_state()
    verifier, challenge = client.create_pkce_pair()
    authorization_url = client.build_authorization_url(
        smart,
        state=state,
        code_challenge=challenge,
    )
    callback = await asyncio.to_thread(
        _read_epic_callback,
        authorization_url,
        config.redirect_uri,
    )
    if callback.get("error"):
        raise RuntimeError(f"Epic authorization failed: {callback['error']}")

    return await client.exchange_code(
        smart,
        code=callback.get("code", ""),
        returned_state=callback.get("state", ""),
        expected_state=state,
        code_verifier=verifier,
    )
