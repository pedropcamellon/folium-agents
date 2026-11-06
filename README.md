# Folium Agents

Python agent components for Folium. The package includes a read-only OpenEMR
FHIR R4 client for the public OpenEMR demo.

## OpenEMR demo connection

The demo login page is
<https://demo.openemr.io/openemr/interface/login/login.php?site=default>. The
FHIR API base URL for its `default` site is
`https://demo.openemr.io/openemr/apis/default/fhir`; the client requests its
`metadata` capability statement. This verifies API connectivity and the FHIR
version without accessing patient records.

Run the interactive menu:

```bash
uv run folium-agents
```

The menu can check connectivity or list a bounded page of patient IDs. The
non-interactive commands remain available as `uv run folium-agents check` and
`uv run folium-agents patients --limit 20`.

By default, the client checks the public demo metadata endpoint without
authentication. Patient search uses the OAuth2 password grant, which is
disabled by default and is not recommended for production. An OpenEMR
administrator must enable it and register an OAuth client with FHIR patient
read/search access (for example, `api:fhir user/Patient.read`).

Provide the authorized test account and OAuth client values as environment
variables. A client secret is needed for confidential OAuth clients and
optional for public clients. Keep credentials private.

```bash
export OPENEMR_USERNAME="your-openemr-user"
export OPENEMR_PASSWORD="your-openemr-password"
export OPENEMR_CLIENT_ID="your-registered-client-id"
export OPENEMR_CLIENT_SECRET="your-client-secret"
uv run folium-agents
```

The client exchanges the credentials for an access token and queries the
FHIR `Patient` search endpoint. It returns patient IDs only, requests only the
`id` element, and limits each request to 100 results. To use a pre-issued bearer
token instead, set `OPENEMR_ACCESS_TOKEN`; the username/password and OAuth
client ID are then not needed. For a different OpenEMR instance, also set
`OPENEMR_FHIR_BASE_URL` and `OPENEMR_OAUTH_TOKEN_URL`.

## Epic sandbox connector

The Epic adapter uses SMART on FHIR discovery, authorization-code exchange,
state validation, and PKCE S256. It can read a single CarePlan by ID and asks
for only the ID, status, subject, and encounter fields. The Epic app must have
the corresponding read API enabled.

Configure these values locally (never commit client secrets or tokens):

```bash
export EPIC_CLIENT_ID="your-sandbox-client-id"
export EPIC_REDIRECT_URI="https://your-host/oauth/callback"
export EPIC_FHIR_ISSUER="https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
```

The CLI loads a `.env` file from the repository root automatically without
overriding environment variables already set by the shell.

For a confidential client, also configure `EPIC_CLIENT_SECRET` and set
`EPIC_TOKEN_AUTH_METHOD` to the method selected during Epic app registration:
`client_secret_post` or `client_secret_basic`. Public clients use `none`.
`EPIC_SCOPE` defaults to `openid fhirUser launch user/CarePlan.rs`.
`uv run folium-agents epic-discover` checks the public sandbox SMART metadata.
OAuth callback hosting and an Epic EHR launch context are required for an
interactive clinician authorization; the SDK intentionally does not reuse
browser-session cookies.

## Development

Requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Scope and safety

The integration only reads the capability statement or patient IDs; it never
modifies records. The public demo is shared and may be reset at any time. Use
only approved test accounts, and prefer authorization-code OAuth over password
grant outside this demo workflow.
