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
    EpicConfig,
    EpicSmartClient,
    EpicToken,
    EpicTokenCache,
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

    resources = [
        resource
        for rest in capabilities.rest
        for resource in rest.resources
    ]
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

    table = Table(title=f"Epic sandbox Patient search ({len(result.patients)} returned)")
    table.add_column("Patient ID", style="cyan")
    table.add_column("Name")
    for patient in result.patients:
        table.add_row(patient.id, patient.display_name)
    console.print(table)


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
