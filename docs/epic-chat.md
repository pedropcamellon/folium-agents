# Epic chart chat: local setup

The local proof runs a Next.js frontend and FastAPI API with Docker Compose.
Epic is the first provider; the API discovers connectors through entry points
so another EHR can implement the same contract without changing chat
orchestration.

Use synthetic Epic sandbox records only. The API performs SMART authorization
with PKCE. Compose persists authorized connections in an encrypted SQLite
database on a named volume, with a separate key volume. The browser stores only
opaque session handles (including a small list of independently authorized
connections), never demographics or chart content. A connection can resume
for up to 24 hours from creation, including across API/container reloads.
OAuth tokens are not written to the browser, host keyring, image, or Terraform
state. Ending a session deletes its local credentials; restarting the API clears
chat history, not the authorized connection. In-progress OAuth/PKCE exchanges
remain memory-only and must restart if the API reloads before callback.
The UI does not provide clinician identity authentication and must not be
exposed beyond local development.

## Epic and model configuration

Set these variables in the repository-root `.env` file. Keep `.env`
untracked and do not paste secrets into source control, chat logs, or issue
files:

```dotenv
EPIC_CLIENT_ID=your-epic-sandbox-client-id
EPIC_REDIRECT_URI=http://localhost:8000/api/epic/callback
EPIC_TOKEN_AUTH_METHOD=none
FOLIUM_AGENTS_FRONTEND_ORIGIN=http://localhost:3000
FOLIUM_AGENTS_MODEL_BASE_URL=https://your-resource.openai.azure.com/openai/v1
FOLIUM_AGENTS_MODEL_NAME=your-azure-model-deployment
FOLIUM_AGENTS_MODEL_API_KEY=replace-with-local-secret
FOLIUM_AGENTS_MODEL_API_KEY_HEADER=api-key
```

Register this exact redirect URI in the Epic sandbox app before starting the
web flow:

```text
http://localhost:8000/api/epic/callback
```

The current Epic connector requests patient-scoped access to
`MedicationRequest`, `AllergyIntolerance`, `Condition`, and read access to
`Patient` for the selected patient's name and date of birth. These resource
types are provisional until the configured Epic sandbox confirms the search
interactions and the app registration grants the required SMART permissions.
`CapabilityStatement` metadata alone does not grant application access.

The model endpoint should use the Azure OpenAI-compatible v1 path, for example
`https://<resource>.openai.azure.com/openai/v1`. Set `FOLIUM_AGENTS_MODEL_NAME`
to the Azure deployment name, not the underlying model family. The API key is
sent only from FastAPI to the model endpoint using the configured header.
Patient chart evidence from this proof is sent to that Azure endpoint to
generate a response; do not use production patient data.

## Run with Docker Compose

From the repository root, set the environment variables above and then:

```bash
docker compose up --build
```

Open `http://localhost:3000`. The root route opens directly to the chat
workspace; select or change the synthetic Patient FHIR ID in the patient
context panel. The app and API bind to loopback ports 3000 and 8000. Authorize
the selected patient through the configured EHR connector. The OAuth redirect
must be registered exactly as shown above. The API disables HTTP access
logging so the authorization code in the callback URL is not written to
container logs. After authorization, the callback returns to the same root
chat view with the patient context active.

The clinical interface is a local synthetic-data demo, not an EHR application.
The browser connects to port 8000 on the same hostname used for the frontend,
supporting both `localhost` and `127.0.0.1`. If the UI reports that it cannot
reach the API, verify both Compose services are running. `0.0.0.0` is a server
bind address, not a browser destination; the frontend maps it to the page's
hostname, or to `localhost` if the page itself was opened with that address.
See the project README for optional frontend API URL configuration.

## Local development and Compose Watch

The root Compose file is for local development. Start FastAPI with reload and
Next.js in development mode:

```bash
docker compose up
```

Source files are mounted for automatic API and frontend reloads. To enable
Compose Watch for dependency-manifest and Dockerfile changes, use:

```bash
docker compose up --watch
```

The Python environment, Node dependencies, and Next.js build cache use named
container volumes. The host `.venv` is intentionally not mounted into the Linux
API container because host-installed binaries may not be compatible with Linux.
Use `docker compose down -v` only when you also want to delete connection
credentials and encryption keys, as well as dependency/build-cache volumes.
The Dockerfiles retain production image targets; the local
Compose file supplies the development commands and mounts.

If Epic displays `Invalid OAuth 2.0 request`, check the sandbox app registration
before changing the patient ID or weakening the requested scopes:

1. Confirm `EPIC_CLIENT_ID` in the local `.env` belongs to the intended
   non-production app.
2. Register `http://localhost:8000/api/epic/callback` exactly. The scheme,
   host, port, and path must match; this is not the frontend URL or the older
   CLI callback.
3. Configure authorization-code flow with PKCE S256. Set
   `EPIC_TOKEN_AUTH_METHOD=none` if the app is registered as a public client;
   otherwise configure the token authentication method required by that app.
4. Ensure the app registration permits the requested scopes:
   `openid`, `fhirUser`, `launch/patient`,
   `patient/MedicationRequest.rs`,
   `patient/AllergyIntolerance.rs`, `patient/Condition.rs`, and
   `patient/Patient.r`.
5. Save the registration, make `.env` match it, and recreate Compose so the API
   uses the updated settings.
6. Retry from `http://localhost:3000` with a known synthetic ID from the
   [Epic sandbox test-patient list](https://fhir.epic.com/Documentation?docId=testpatients).
   Confirm the callback returns to the chat with that same patient context.

Do not remove resource scopes just to bypass the authorization error; the chat
needs those grants to retrieve evidence. If the registration does not support a
requested scope, record that resource as unavailable. Do not share the full
authorization URL; it contains temporary state and PKCE request values.

Use `docker compose down` to stop the local app without deleting its volumes.

## Connection retention and patient isolation

Compose sets `FOLIUM_AGENTS_CONNECTION_DB` and
`FOLIUM_AGENTS_CONNECTION_KEY_FILE`. The API creates a private Fernet key on
first start in `api-connection-keys`, separate from `api-connections`. Both are
required to restore credentials. Keep key permissions at `0600`; storage errors
or an invalid key fail closed rather than falling back to plaintext. Back up
keys separately with restricted access. Losing a key requires reauthorization;
for this local slice, rotation means ending connections, deleting the old state
and key volumes, and authorizing again. Host/container administrators can read
both volumes: this is not protection against a compromised runtime.

Outside Compose, persistence is opt-in: configure both paths in a private local
directory (for example `.connections/`, which is ignored). With neither setting,
connections remain memory-only. Never put key contents in source, environment
examples, images, logs or Terraform. A production deployment needs a managed
secret/key service and an explicitly reviewed retention/rotation policy.

Only patient context, provider/configuration binding, access/refresh tokens and
absolute expiry timestamps are encrypted and saved. Neither FHIR responses nor
chat transcripts, authorization codes or PKCE secrets are persisted. Unexpired
access tokens are reused; refresh occurs only when Epic actually supplies a
refresh token. Rotation responses replace that token, while omitted refresh
tokens preserve the previous grant. Invalid refresh grants, patient mismatches,
or FHIR 401 responses discard local credentials and require authorization again.
Transient upstream failures do not discard a refresh grant. No additional SMART
scopes, including `offline_access`, are silently requested.

Use **Authorize another patient** to perform a separate SMART authorization
without destroying a previous connection; use the connection selector to return
to one of up to twelve saved browser handles. Every request checks that the
selected patient matches that connection's token. **End session** deletes only
that local connection, including after a restart. It does not revoke the grant
at Epic; revoke upstream consent through Epic when required. An in-flight
request may still finish. Expired records are pruned on storage operations.

This is a single API worker/local-instance design, not distributed session
management. Refresh is serialized within that connector process. Do not share
this database across concurrent replicas/workers. There is no authenticated
clinician or organization binding: opaque browser handles are bearer secrets,
not proof of clinician identity. General user-level multi-patient access still
requires Epic application approval, appropriate user-level scopes, and verified
clinician/organization identity. Multiple separately authorized patient contexts
do not confer permission to enumerate or query arbitrary patients.

## Safe failure diagnostics

Backend JSON events cover OAuth start/exchange/refresh, session restoration and
local revocation, FHIR failures, model/validation failures and API status. Each
response carries a server-generated `X-Correlation-ID`, exposed through CORS.
The browser console logs only operation, numeric status, error class or that
reference; server errors display the reference for troubleshooting. Search the
API container logs for it with `docker compose logs api`. Health checks are
excluded from routine diagnostic events.

Logs never include raw exception messages, request bodies, patient identifiers,
chart content, access/refresh tokens, codes or authorization URLs. HTTP access
logs remain disabled and provider HTTP client logging is restricted to warnings.
Keep that policy in any reverse proxy too; callback query strings and session
paths contain secrets. An OAuth error rendered on Epic's own page occurs before
our callback and cannot be diagnosed from our response reference: verify the app
registration/redirect/scopes above without sharing the authorization URL.

## Provision the Azure model with Terraform

Terraform creates a resource group, Azure OpenAI account, and a model
deployment. State is stored in an Azure Blob Storage backend; the storage
account and container must already exist and are not created by this module.
Use a dedicated state container and grant the local Azure identity the
`Storage Blob Data Contributor` role on it. Region, model, version, deployment
SKU, capacity, account name, deployment name, and resource group are required
inputs. No model is selected automatically because model availability,
tool-calling support, quota, and cost vary by region and subscription.

Sign in locally with Azure CLI and initialize the backend with the existing
state resource group, storage account, and container. Keep backend values in
your shell or a local untracked config file; do not commit credentials or
Terraform state:

```bash
cd terraform
az login
export ARM_SUBSCRIPTION_ID=<subscription-id>
az account set --subscription "$ARM_SUBSCRIPTION_ID"
terraform init -backend-config="resource_group_name=<state-resource-group>" \
  -backend-config="storage_account_name=<state-storage-account>" \
  -backend-config="container_name=<state-container>" \
  -backend-config="key=folium-agents/model.tfstate" \
  -backend-config="use_azuread_auth=true"
terraform fmt -check -recursive
terraform validate
```

For an existing local state, use `terraform init -migrate-state` instead of
plain `terraform init` after supplying the same backend configuration. Use
`terraform plan` with explicit values after selecting an available model and
region. Review the plan and expected cost before applying. Applying resources
is an explicit operator action; this repository does not auto-apply cloud
infrastructure. Terraform does not output model keys. Retrieve/manage the
Azure key through an approved secret-handling path and supply it to local
Compose as `FOLIUM_AGENTS_MODEL_API_KEY`.

## Local development without containers

The API and frontend can run separately when a local Python and Node toolchain
is available:

```bash
uv sync
uv run folium-agents-api
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm dev
```

The Epic callback URL must still match the local settings. By default, the
frontend uses its current hostname with port 8000 for the API.
No chart transcript is persisted. Connector access, configured model
availability, and live Epic scopes must be tested separately from offline
unit tests.
