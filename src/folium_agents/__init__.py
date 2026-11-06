"""Command-line entry points for the Folium Agents EHR connectors."""

import argparse
import asyncio
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse

from rich.console import Console
from rich.table import Table

from folium_agents.epic import EpicConfig, EpicSmartClient


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


async def _discover_epic() -> None:
    config = EpicConfig.from_environment()
    smart = await EpicSmartClient(config).discover()
    print(f"Authorization endpoint: {smart.authorization_endpoint}")
    print(f"Token endpoint: {smart.token_endpoint}")
    print(
        "PKCE S256: "
        f"{'supported' if 'S256' in smart.code_challenge_methods_supported else 'not supported'}"
    )


async def _epic_patient_search(limit: int) -> list[tuple[str, str]]:
    config = EpicConfig.from_environment()
    client = EpicSmartClient(config)
    smart = await client.discover()
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

    token = await client.exchange_code(
        smart,
        code=callback.get("code", ""),
        returned_state=callback.get("state", ""),
        expected_state=state,
        code_verifier=verifier,
    )
    result = await client.search_patients(token.access_token, limit=limit)
    return [(patient.id, patient.display_name) for patient in result.patients]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read sample patients from the Epic FHIR sandbox."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("patients", "epic-discover"),
        default="patients",
        help="list sandbox sample patients or inspect SMART metadata",
    )
    parser.add_argument("--limit", type=int, default=10, help="maximum results (1-20)")
    args = parser.parse_args()
    console = Console()
    if args.command == "epic-discover":
        asyncio.run(_discover_epic())
        return
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be between 1 and 20")

    patients = asyncio.run(_epic_patient_search(args.limit))
    table = Table(title=f"Epic sandbox sample patients ({len(patients)} returned)")
    table.add_column("Patient ID", style="cyan")
    table.add_column("Name")
    for patient_id, name in patients:
        table.add_row(patient_id, name)
    console.print(table)
