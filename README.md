# Folium Agents

Folium Agents is an independent workspace for developing reusable agent workflows that can work with different electronic health record (EHR) systems. The project separates agent behavior from vendor-specific connectors, which own authentication, API calls, and mapping EHR data into stable agent-facing contracts.

Epic integration is in progress.

## Run the app

Set these variables in the repository-root `.env` file. Keep `.env` untracked and do not paste secrets into source control, chat logs, or issue files:

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

Configure a non-production Epic app for provider-level patient search and the approved read-only clinical and claims access. Register the exact callback `http://localhost:8000/api/epic/callback`; configure the client authentication method and required Epic interactions for the app. Use synthetic sandbox data only.

If Epic displays `Invalid OAuth 2.0 request`, verify the client ID, exact callback, authorization-code flow with PKCE S256, token authentication method, and required Patient.Search, Clinical, and Claims interactions. Recreate the API service after changing `.env`. Do not share the full authorization URL.

Start Docker Desktop. From the repository root, run:

```bash
docker compose up --build
```

Open **http://localhost:3000** after the services start. Patient Search and Chat are separate pages; the selected patient appears in the workspace scope outside the conversation. Search for a synthetic patient, select a result, and complete the patient-scoped chat authorization. The API runs at http://localhost:8000; the CLI is optional and does not start with the web app.

Use `docker compose up --watch` when developing with Compose Watch.

For local development without containers, run the API and frontend in separate terminals from the repository root.

API:

```bash
uv sync
uv run folium-agents-api
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Stop Compose with `Ctrl+C`, then run `docker compose down`. Do not add `-v` unless you intend to delete saved connections and keys.

## Architecture

Connectors are developed and validated independently against authorized sandbox or synthetic data. They should use supported APIs, least-privilege access, preserve source provenance, and avoid writes unless a separately reviewed workflow explicitly requires them.

The harness core provides vendor-neutral agent capabilities and discovers optional modules through package entry points. Modules own their domain APIs, authentication, data mapping, and module-specific commands; the core does not import concrete EHR implementations.

## Project layout

- `src/folium_agents/cli.py` — shared command-line routing
- `src/folium_agents/core/` — module contract and vendor-neutral runtime
- `src/folium_agents/core/ehr.py` — provider-neutral EHR chat contract
- `src/folium_agents/epic/` — Epic SMART/FHIR connector and CLI
- `src/folium_agents/api/` — FastAPI chat API and provider registry
- `frontend/` — Next.js clinician chat
- `terraform/` — Azure OpenAI account and model deployment
- `docker-compose.yml` — local web app services
- `src/folium_agents/openemr.py` — read-only OpenEMR FHIR client
- `docs/epic-sandbox.md` — Epic sandbox setup and current proof
- `docs/epic-chat.md` — Epic chat feature overview, implemented behavior, and boundaries
- `docs/openemr-demo.md` — OpenEMR demo setup and current proof

## Development

Local Compose currently enables `FOLIUM_AGENTS_LOG_MODEL_RESPONSES=true` and disables required citations with `FOLIUM_AGENTS_REQUIRE_MODEL_CITATIONS=false` for synthetic-data debugging. Model answer text appears in API container logs. Never enable response logging with real patient data or production log sinks. Outside Compose, response logging defaults off and citations remain required.

Requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
```

Folium Agents lets a user talk to their EHR through a local FastAPI + Next.js app. The API discovers EHR connectors through entry points; Epic is one connector and does not define the product or chat workflow. See [docs/epic-chat.md](docs/epic-chat.md) for the Epic feature overview and current implementation boundaries.

Compose retains separately authorized patient connections across API reloads using encrypted storage and a separate key volume; chart/chat contents are not persisted. See the chat guide for expiry, local revocation, safe correlation-ID diagnostics and the remaining clinician-identity/Epic-approval limitations.

For local Luna chat, create the ignored `.env.azure-local` file and keep its Azure key there, not in Compose or source control. The API service loads this file on every container creation. Set `FOLIUM_AGENTS_MODEL_BASE_URL` to `https://folium-agents-dev-luna.openai.azure.com/openai/v1`, `FOLIUM_AGENTS_MODEL_NAME=gpt-6-luna`, `FOLIUM_AGENTS_MODEL_API_KEY` to the key from the Azure account's Keys and Endpoint page, and `FOLIUM_AGENTS_MODEL_REASONING_EFFORT=low`. The API uses the OpenAI SDK Responses API so Luna can use function tools with low reasoning effort.

The `terraform/dev.backend.hcl` file holds the Azure Blob backend settings. Initialize with `terraform -chdir=terraform init -backend-config=dev.backend.hcl`, then run `terraform -chdir=terraform plan` or `apply`. Azure CLI authentication is used for remote state; no storage key is required. Supply resource variables through Terraform's standard variable mechanisms.

### Frontend API URL

Compose defaults `NEXT_PUBLIC_FOLIUM_AGENTS_API_URL` to `http://localhost:8000` and passes overrides to the frontend build and development server. If running the frontend outside Compose, set a URL the browser can reach; when unset, the frontend logs an error and falls back to the page hostname on port 8000. Do not use the Compose-only hostname `api`.

The local API accepts frontend origins on port 3000 for `localhost`, `127.0.0.1`, and `0.0.0.0`. Prefer opening `http://localhost:3000`; `0.0.0.0` is normally a server bind address, but opening it in a browser produces a distinct origin that must also pass the API's CORS preflight.
