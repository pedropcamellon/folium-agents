"""Command-line entry point for the Folium Agents web API."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "folium_agents.api.app:app",
        host=os.environ.get("FOLIUM_AGENTS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("FOLIUM_AGENTS_API_PORT", "8000")),
        access_log=False,
    )
