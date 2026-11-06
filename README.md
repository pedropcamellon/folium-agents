# Folium Agents

Folium Agents is an independent workspace for developing reusable agent
workflows that can work with different electronic health record (EHR) systems.
The project separates agent behavior from vendor-specific connectors, which
own authentication, API calls, and mapping EHR data into stable agent-facing
contracts.

Connectors are developed and validated independently against authorized
sandbox or synthetic data. They should use supported APIs, least-privilege
access, preserve source provenance, and avoid writes unless a separately
reviewed workflow explicitly requires them.

The harness core provides vendor-neutral agent capabilities and discovers
optional modules through package entry points. Modules own their domain APIs,
authentication, data mapping, and module-specific commands; the core does not
import concrete EHR implementations.

## Project layout

- `src/folium_agents/cli.py` — shared command-line routing
- `src/folium_agents/core/` — module contract and vendor-neutral runtime
- `src/folium_agents/epic/` — Epic SMART/FHIR client, secure token cache, and CLI
- `docs/epic-sandbox.md` — Epic sandbox setup and current proof

## Development

Requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
```

Connector-specific configuration and run instructions belong in their
respective documentation so the project overview remains EHR-neutral.
