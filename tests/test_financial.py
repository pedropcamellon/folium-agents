"""Independent synthetic expectations; fake models test the harness, not quality."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from folium_agents.api import app as api
from folium_agents.financial import MockFinancialAPI, investigate


def test_preview_expected_cases_and_no_mutation():
    api = MockFinancialAPI()
    before = api.snapshot()
    cases = json.loads(Path(__file__).with_name("financial_cases.json").read_text())
    for case in cases["development"] + cases["holdout"]:
        claim = case["claim"]
        preview = api.read("preview_posting", claim)
        if "after" in case:
            assert preview["valid"]
            assert preview["afterCents"] == case["after"]
        else:
            assert not preview["valid"]
    assert api.snapshot() == before
    with pytest.raises(ValueError):
        api.read("get_claim", "foreign")


class Model:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.responses = self

    async def create(self, **kwargs):
        return next(self.steps)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def call(name, arguments="{}"):
    return NS(
        id="response",
        output=[
            NS(type="function_call", name=name, arguments=arguments, call_id="call")
        ],
    )


def answer(action, citations):
    return NS(
        id="final",
        output=[],
        output_text=json.dumps({"action": action, "citations": citations}),
    )


def test_tool_using_run_and_scoped_evidence():
    model = Model(
        [
            call("get_claim"),
            call("get_remittances"),
            call("get_postings"),
            call("preview_posting"),
            answer("review_preview", ["SYN-001", "REM-001"]),
        ]
    )
    result = asyncio.run(investigate("SYN-001", model, "fake", "low"))
    assert result.status == "completed"
    assert result.preview is not None
    assert result.preview["afterCents"] == 2000
    assert result.human_review_required
    assert len(result.trace) == 4
    assert result.claim_id == "SYN-001"


def test_api_serves_claims_and_runs_the_tool_agent(monkeypatch):
    model = Model(
        [
            call("get_claim"),
            call("get_remittances"),
            call("get_postings"),
            call("preview_posting"),
            answer("review_preview", ["SYN-001", "REM-001"]),
        ]
    )
    monkeypatch.setattr(api.settings, "model_api_key", "test-key")
    monkeypatch.setattr(api.settings, "model_name", "test-model")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.invalid")
    monkeypatch.setattr(api, "AsyncOpenAI", lambda **kwargs: model)

    with TestClient(api.app) as client:
        claims = client.get("/api/financial/claims")
        investigation = client.post("/api/financial/claims/SYN-001/investigate")

    assert claims.status_code == 200
    assert claims.json()[0]["claimId"] == "SYN-001"
    assert investigation.status_code == 200
    assert investigation.json()["status"] == "completed"
    assert investigation.json()["preview"]["afterCents"] == 2000


@pytest.mark.parametrize(
    "steps,limit,status",
    [
        ([call("get_claim", '{"claimId":"SYN-002"}')], 8, "failed"),
        ([call("post_payment")], 8, "failed"),
        ([answer("review_preview", ["invented"])], 8, "failed"),
        ([call("get_claim"), call("get_claim")], 1, "incomplete"),
        ([call("get_claim"), answer("review_preview", ["SYN-001"])], 8, "failed"),
    ],
)
def test_explicit_failure_and_bound(steps, limit, status):
    result = asyncio.run(investigate("SYN-001", Model(steps), "fake", "low", limit))
    assert result.status == status
    assert result.error
    assert result.action != "review_preview"
