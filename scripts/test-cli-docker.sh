#!/usr/bin/env bash
set -euo pipefail

project_name="folium-agents-cli-smoke-$$"
container_name="${project_name}-callback"

compose() {
  docker compose --project-name "$project_name" --profile cli "$@"
}

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

compose build cli
compose run --rm cli --help
compose run --rm cli epic discover --help
compose run --rm \
  --env EPIC_CLIENT_ID=smoke-client \
  --env EPIC_REDIRECT_URI=http://localhost:8765/callback \
  --entrypoint python cli -c '
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/.well-known/smart-configuration"):
            payload = {
                "authorization_endpoint": "https://example.test/authorize",
                "token_endpoint": "https://example.test/token",
                "code_challenge_methods_supported": ["S256"],
            }
        elif self.path.endswith("/metadata"):
            payload = {
                "resourceType": "CapabilityStatement",
                "rest": [{"resource": [{"type": "Patient"}]}],
            }
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
os.environ["EPIC_ISSUER"] = f"http://127.0.0.1:{server.server_port}/fhir"
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    from folium_agents.core.cli import main
    main(["epic", "discover"])
finally:
    server.shutdown()
    server.server_close()
    thread.join()
'

compose run --rm \
  --env EPIC_CLIENT_ID=smoke-client \
  --env EPIC_REDIRECT_URI=http://localhost:8765/callback \
  --env EPIC_TOKEN_CACHE_ENABLED=false \
  --entrypoint python cli -c '
import keyring
from folium_agents.epic.epic import EpicConfig, EpicTokenCache
from folium_agents.epic.models import EpicToken

def unexpected_keyring_access(*args, **kwargs):
    raise AssertionError("Container token-cache operations must not access keyring")

keyring.get_password = unexpected_keyring_access
keyring.set_password = unexpected_keyring_access
keyring.delete_password = unexpected_keyring_access
cache = EpicTokenCache(EpicConfig(
    client_id="smoke-client",
    redirect_uri="http://localhost:8765/callback",
))
assert cache.load() is None
cache.save(EpicToken(access_token="synthetic-token", expires_in=60))
cache.clear()
'

compose run --detach --name "$container_name" --service-ports \
  --env EPIC_CLIENT_ID=smoke-client \
  --env EPIC_REDIRECT_URI=http://localhost:8765/callback \
  --entrypoint python cli -c '
from folium_agents.epic import epic_cli
epic_cli.webbrowser.open = lambda url: True
print(epic_cli._read_epic_callback(
    "https://example.test/authorize",
    "http://localhost:8765/callback",
))
'

curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-all-errors \
  --retry-delay 1 "http://127.0.0.1:8765/callback?code=synthetic-code&state=synthetic-state"
docker wait "$container_name" >/dev/null
docker logs "$container_name" | grep -F \
  "{'code': 'synthetic-code', 'state': 'synthetic-state'}"
