#!/bin/sh
set -eu

EPIC_TOKEN_CACHE_ENABLED="${EPIC_TOKEN_CACHE_ENABLED:-false}"
export EPIC_TOKEN_CACHE_ENABLED

exec folium-agents "$@"
