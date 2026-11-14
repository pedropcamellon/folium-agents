FROM ghcr.io/astral-sh/uv:0.11.7 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    FOLIUM_AGENTS_EPIC_CALLBACK_BIND_HOST=0.0.0.0

COPY scripts/cli-entrypoint.sh /usr/local/bin/cli-entrypoint
RUN chmod 755 /usr/local/bin/cli-entrypoint

USER 10001:10001
EXPOSE 8765

ENTRYPOINT ["/usr/local/bin/cli-entrypoint"]
CMD ["--help"]
