import asyncio
from types import SimpleNamespace
from typing import Self
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from folium_agents.api import app as api
from folium_agents.api import models as api_models
from folium_agents.core.ehr import (
    AuthorizationRequest,
    ChartEvidence,
    EHRConnectionStatus,
    EvidenceRecord,
    PatientDemographics,
)


def _mock_openai(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict[str, object]],
    requests: list[dict[str, object]] | None = None,
) -> None:
    captured = requests if requests is not None else []

    class FakeAsyncOpenAI:
        def __init__(self, **options: object) -> None:
            assert options["timeout"] == 45.0
            self.responses = self

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def create(self, **request: object) -> SimpleNamespace:
            captured.append(request)
            payload = responses.pop(0)
            message = payload["choices"][0]["message"]
            calls = [
                SimpleNamespace(
                    type="function_call",
                    name=tool_call["function"]["name"],
                    arguments=tool_call["function"]["arguments"],
                    call_id=tool_call["id"],
                )
                for tool_call in message.get("tool_calls", [])
            ]
            return SimpleNamespace(
                id=f"response-{len(captured)}",
                output=calls,
                output_text=message.get("content") or "",
            )

    monkeypatch.setattr(api, "AsyncOpenAI", FakeAsyncOpenAI)


@pytest.fixture(autouse=True)
def clear_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    api.sessions.clear()
    monkeypatch.setattr(api, "store", None)
    monkeypatch.setattr(api.settings, "log_model_responses", False)
    monkeypatch.setattr(api.settings, "require_model_citations", True)


def test_missing_citations_fail_without_additional_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unsupported chart answers from reaching users without extra model costs."""
    # Arrange: provide a chart answer that omits its supporting records.
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "function": {
                                    "name": "get_patient_chart",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": '{"answer":"Recorded condition.","citations":[]}'
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"answer":"Recorded condition.","citations":'
                            '[{"sourceType":"Condition","sourceId":"condition-1"}]}'
                        )
                    }
                }
            ]
        },
    ]
    requests: list[dict[str, object]] = []
    _mock_openai(monkeypatch, responses, requests)
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")

    async def retrieve() -> str:
        return '{"records":[{"source_type":"Condition","source_id":"condition-1"}]}'

    # Act: ask the assistant to compose an answer from the supplied chart.
    answer = asyncio.run(
        api._ask_model(
            [api_models.ChatMessage(role="user", content="Summarize this chart")],
            retrieve,
        )
    )
    sources = [
        api_models.ChatSource(
            source_type="Condition",
            source_id="condition-1",
            title="Synthetic condition",
        )
    ]
    # Assert: reject the unsupported answer without paying for another attempt.
    assert len(requests) == 2
    with pytest.raises(ValueError, match="without citing"):
        api._render_grounded_answer(answer, sources, [])


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3000", "http://0.0.0.0:3000"],
)
def test_api_accepts_local_frontend_origins(origin: str) -> None:
    """Let users open the local workspace using supported development addresses."""
    # Act: ask whether this local workspace may contact the service.
    response = TestClient(api.app).options(
        "/api/sessions",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    # Assert: allow the supported local workspace to connect.
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-private-network"] == "true"


def test_api_rejects_private_network_preflight_from_untrusted_origin() -> None:
    """Prevent unrelated websites from accessing the local clinical workspace."""
    # Act: attempt access from an unrelated website.
    response = TestClient(api.app).options(
        "/api/sessions",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    # Assert: deny the unrelated website access.
    assert response.status_code == 400
    assert "Disallowed CORS origin" in response.text


class FakeConnector:
    name = "fake"

    def __init__(self, *, connected: bool = False) -> None:
        self.started: list[tuple[str, str]] = []
        self.completed: list[tuple[str, str, str]] = []
        self.ended: list[str] = []
        self.connected = connected

    async def start_authorization(
        self,
        session_id: str,
        patient_id: str,
    ) -> AuthorizationRequest:
        self.started.append((session_id, patient_id))
        return AuthorizationRequest(
            state="test-state",
            authorization_url="https://ehr.example.test/authorize",
        )

    async def complete_authorization(
        self,
        session_id: str,
        *,
        state: str,
        code: str,
    ) -> None:
        self.completed.append((session_id, state, code))
        self.connected = True

    async def get_connection_status(
        self,
        _session_id: str,
        patient_id: str,
    ) -> EHRConnectionStatus:
        return EHRConnectionStatus(
            connected=self.connected,
            patient_id=patient_id,
        )

    async def get_patient_demographics(
        self,
        _session_id: str,
        patient_id: str,
    ) -> PatientDemographics:
        return PatientDemographics(
            patient_id=patient_id,
            given_name="Synthetic",
            family_name="Patient",
            birth_date="1980-01-01",
        )

    async def retrieve_patient_chart(
        self,
        _session_id: str,
        patient_id: str,
    ) -> ChartEvidence:
        return ChartEvidence(patient_id, [], [], True)

    def end_session(self, session_id: str) -> None:
        self.ended.append(session_id)


def test_chat_api_returns_answer_and_sources_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show readable answers with supporting records listed once in the source panel."""
    # Arrange: supply an authorized chart and a predictable, sourced model answer.
    class ChartConnector(FakeConnector):
        async def retrieve_patient_chart(
            self, _session_id: str, patient_id: str
        ) -> ChartEvidence:
            return ChartEvidence(
                patient_id,
                [
                    EvidenceRecord(
                        source_type="Condition",
                        source_id="condition-1",
                        title="Synthetic condition",
                        date=None,
                        status="active",
                        data={},
                    )
                ],
                ["Synthetic incomplete retrieval warning"],
                False,
            )

    monkeypatch.setattr(api, "connectors", {"fake": ChartConnector(connected=True)})
    storage = Mock()
    storage.load.return_value = None
    monkeypatch.setattr(api, "store", storage)
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")
    api.sessions["synthetic-session"] = api_models.ChatSessionState(
        patient_id="synthetic-patient", provider_id="fake", authorization_state=""
    )
    requests: list[dict[str, object]] = []
    _mock_openai(
        monkeypatch,
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "function": {
                                        "name": "get_patient_chart",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"answer":"Recorded condition.","citations":'
                                '[{"sourceType":"Condition","sourceId":"condition-1"}]}'
                            )
                        }
                    }
                ]
            },
        ],
        requests,
    )

    # Act: ask a chart question through the same endpoint used by the workspace.
    response = TestClient(api.app).post(
        "/api/sessions/synthetic-session/chat",
        json={"question": "Summarize this chart"},
    )

    # Assert: keep answer text, supporting records, and retrieval warnings separate.
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Recorded condition."
    assert "Sources:" not in payload["answer"]
    assert payload["sources"] == [
        {
            "sourceType": "Condition",
            "sourceId": "condition-1",
            "title": "Synthetic condition",
            "date": None,
            "status": "active",
        }
    ]
    assert payload["warnings"] == ["Synthetic incomplete retrieval warning"]
    assert len(requests) == 2
    assert "displays sources separately" in requests[0]["input"][0]["content"]


def test_create_session_uses_registered_provider_neutrally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Let users connect through their selected EHR without changing the chat flow."""
    # Arrange: make a supported EHR available.
    fake = FakeConnector()
    monkeypatch.setattr(api, "connectors", {"fake": fake})

    # Act: request a new connection for the selected patient.
    response = TestClient(api.app).post(
        "/api/sessions",
        json={"patientId": "synthetic-patient", "providerId": "fake"},
    )

    # Assert: preserve the selected patient and use the selected EHR.
    assert response.status_code == 200
    result = response.json()
    assert result["patientId"] == "synthetic-patient"
    assert result["authorizationUrl"] == "https://ehr.example.test/authorize"
    assert fake.started == [(result["sessionId"], "synthetic-patient")]
    assert api.sessions[result["sessionId"]].provider_id == "fake"


def test_authorization_callback_delegates_to_selected_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return users to their workspace after their selected EHR grants access."""
    # Arrange: start an authorization request for the selected EHR.
    fake = FakeConnector()
    monkeypatch.setattr(api, "connectors", {"fake": fake})
    session_id = "session-for-test"
    api.sessions[session_id] = api_models.ChatSessionState(
        patient_id="synthetic-patient",
        provider_id="fake",
        authorization_state="test-state",
    )

    with TestClient(api.app, follow_redirects=False) as client:
        # Act: complete the EHR authorization.
        response = client.get("/api/fake/callback?state=test-state&code=synthetic-code")

    # Assert: return to the correct workspace and consume the authorization state.
    assert response.status_code == 307
    assert response.headers["location"].endswith(f"/?session_id={session_id}")
    assert fake.completed == [(session_id, "test-state", "synthetic-code")]
    assert api.sessions[session_id].authorization_state == ""


def test_session_chat_requires_a_valid_epic_session() -> None:
    """Prevent chart conversations when the user's connection is unavailable."""
    # Act: submit a chart question without a valid connection.
    response = TestClient(api.app).post(
        "/api/sessions/missing/chat",
        json={"question": "Summarize this chart"},
    )

    # Assert: refuse the unavailable connection.
    assert response.status_code == 404


def test_patient_profile_uses_connected_patient_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show details for the authorized patient rather than a different patient."""
    # Arrange: connect a session to a known synthetic patient.
    fake = FakeConnector(connected=True)
    monkeypatch.setattr(api, "connectors", {"fake": fake})
    session_id = "session-with-patient-context"
    api.sessions[session_id] = api_models.ChatSessionState(
        patient_id="synthetic-patient",
        provider_id="fake",
        authorization_state="",
    )

    # Act: request the connected patient's details.
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/patient")

    # Assert: show only the expected patient's details.
    assert response.status_code == 200
    assert response.json() == {
        "patientId": "synthetic-patient",
        "givenName": "Synthetic",
        "familyName": "Patient",
        "birthDate": "1980-01-01",
    }


def test_patient_profile_is_not_loaded_before_ehr_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep patient details private until the EHR grants access."""
    # Arrange: select a patient without granting access.
    fake = FakeConnector(connected=False)
    monkeypatch.setattr(api, "connectors", {"fake": fake})
    session_id = "session-without-authorization"
    api.sessions[session_id] = api_models.ChatSessionState(
        patient_id="synthetic-patient",
        provider_id="fake",
        authorization_state="test-state",
    )

    # Act: try to load patient details before authorization.
    response = TestClient(api.app).get(f"/api/sessions/{session_id}/patient")

    # Assert: withhold the patient's details.
    assert response.status_code == 401
    assert "patient details" in response.json()["detail"].lower()


def test_reset_ends_connector_and_removes_in_memory_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End the patient's connection when the user ends the session."""
    # Arrange: create an active patient connection.
    fake = FakeConnector(connected=True)
    monkeypatch.setattr(api, "connectors", {"fake": fake})
    session_id = "session-to-reset"
    api.sessions[session_id] = api_models.ChatSessionState(
        patient_id="synthetic-patient",
        provider_id="fake",
        authorization_state="",
    )

    # Act: end the session.
    response = TestClient(api.app).delete(f"/api/sessions/{session_id}")

    # Assert: remove both the workspace session and its EHR connection.
    assert response.status_code == 204
    assert session_id not in api.sessions
    assert fake.ended == [session_id]


def test_chat_hides_model_configuration_details_from_user(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Give users a safe failure message while keeping useful operator diagnostics."""
    # Arrange: simulate a missing model credential on an authorized connection.
    fake = FakeConnector(connected=True)
    monkeypatch.setattr(api, "connectors", {"fake": fake})
    monkeypatch.setattr(api.settings, "model_api_key", "")
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")
    session_id = "session-with-missing-model-key"
    api.sessions[session_id] = api_models.ChatSessionState(
        patient_id="synthetic-patient",
        provider_id="fake",
        authorization_state="",
    )

    # Act: submit a question while model configuration is incomplete.
    with caplog.at_level("ERROR", logger=api.__name__):
        response = TestClient(api.app).post(
            f"/api/sessions/{session_id}/chat",
            json={"question": "Summarize this chart"},
        )

    # Assert: show a safe message and retain operator-only diagnostics.
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The chart assistant could not complete this request. Please try again later."
    )
    assert "FOLIUM_AGENTS_MODEL_API_KEY is not configured." in caplog.text
    assert "could not retrieve or compose a grounded answer" not in response.text


def test_chat_renderer_requires_citations_from_retrieved_sources() -> None:
    """Keep a supported answer readable without repeating the source panel."""
    # Arrange: provide an answer supported by an available chart record.
    answer = api_models.GroundedAnswer(
        answer="Recorded condition.",
        citations=[
            api_models.SourceCitation(source_type="Condition", source_id="condition-1")
        ],
    )
    sources = [
        api_models.ChatSource(
            source_type="Condition",
            source_id="condition-1",
            title="Example condition",
        )
    ]

    # Act: prepare the supported answer for display.
    rendered = api._render_grounded_answer(answer, sources, [])

    # Assert: do not duplicate references in the answer text.
    assert rendered == "Recorded condition."


def test_chat_renderer_rejects_invented_source_ids() -> None:
    """Reject answers that claim support from records outside the patient's chart."""
    # Arrange: supply a citation that does not match the available evidence.
    answer = api_models.GroundedAnswer(
        answer="Unsupported claim.",
        citations=[
            api_models.SourceCitation(
                source_type="Condition",
                source_id="not-returned",
            )
        ],
    )
    sources = [
        api_models.ChatSource(
            source_type="AllergyIntolerance",
            source_id="allergy-1",
            title="Example allergy",
        )
    ]

    # Act and assert: reject the answer rather than display invented evidence.
    with pytest.raises(ValueError, match="not returned"):
        api._render_grounded_answer(answer, sources, [])


def test_chat_renderer_discloses_empty_or_warned_searches() -> None:
    """Tell users when missing or incomplete records prevent a reliable answer."""
    # Arrange: provide a model claim without supporting chart records.
    answer = api_models.GroundedAnswer(answer="Model-generated claim.", citations=[])

    # Act: prepare answers for missing records and incomplete retrieval.
    no_records = api._render_grounded_answer(answer, [], [])
    incomplete = api._render_grounded_answer(answer, [], ["Condition warning/error"])

    # Assert: disclose uncertainty instead of claiming the patient has no history.
    assert "does not establish" in no_records
    assert "no usable records" in incomplete


def test_model_requires_registered_chart_tool_before_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the assistant to consult the patient's chart before answering."""
    # Arrange: simulate chart retrieval followed by a supported answer.
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "function": {
                                    "name": "get_patient_chart",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"answer":"Grounded chart response.",'
                            '"citations":[{"sourceType":"Condition",'
                            '"sourceId":"condition-1"}]}'
                        )
                    }
                }
            ]
        },
    ]
    calls: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 45.0

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> httpx.Response:
            calls.append(json)
            return httpx.Response(
                200,
                json=responses.pop(0),
                request=httpx.Request("POST", "https://model.example.test/chat"),
            )

    async def retrieve() -> str:
        return '{"patient_id":"synthetic-patient"}'

    _mock_openai(monkeypatch, responses, calls)
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")

    # Act: ask the assistant to answer using the registered chart reader.
    answer = asyncio.run(
        api._ask_model(
            [api_models.ChatMessage(role="user", content="Summarize this chart")],
            retrieve,
        )
    )

    # Assert: retrieve evidence before returning the supported answer.
    assert answer.answer == "Grounded chart response."
    assert answer.citations[0].source_id == "condition-1"
    assert calls[0]["tool_choice"] == "required"
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert calls[0]["tool_choice"] == "required"
    assert calls[1]["previous_response_id"] == "response-1"
    assert len(calls) == 2


def test_model_preserves_follow_up_context_and_multiresource_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep follow-up answers relevant and supported across different chart records."""
    # Arrange: provide prior conversation and evidence from several record types.
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "function": {
                                    "name": "get_patient_chart",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"answer":"The chart includes a medication, condition, '
                            'and allergy record.","citations":['
                            '{"sourceType":"MedicationRequest",'
                            '"sourceId":"medication-1"},'
                            '{"sourceType":"Condition","sourceId":"condition-1"},'
                            '{"sourceType":"AllergyIntolerance",'
                            '"sourceId":"allergy-1"}]}'
                        )
                    }
                }
            ]
        },
    ]
    requests: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 45.0

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> httpx.Response:
            requests.append(json)
            return httpx.Response(
                200,
                json=responses.pop(0),
                request=httpx.Request("POST", url),
            )

    async def retrieve() -> str:
        return (
            '{"patient_id":"synthetic-patient","sources":['
            '{"source_type":"MedicationRequest","source_id":"medication-1"},'
            '{"source_type":"Condition","source_id":"condition-1"},'
            '{"source_type":"AllergyIntolerance","source_id":"allergy-1"}]}'
        )

    _mock_openai(monkeypatch, responses, requests)
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")
    messages = [
        api_models.ChatMessage(role="user", content="Summarize my chart."),
        api_models.ChatMessage(
            role="assistant",
            content="The chart includes three relevant record types.",
        ),
        api_models.ChatMessage(
            role="user",
            content="What do the medication, condition, and allergy records show?",
        ),
    ]

    # Act: ask the follow-up question using the previous conversation.
    answer = asyncio.run(api._ask_model(messages, retrieve))
    sources = [
        api_models.ChatSource(source_type=source_type, source_id=source_id, title="")
        for source_type, source_id in [
            ("MedicationRequest", "medication-1"),
            ("Condition", "condition-1"),
            ("AllergyIntolerance", "allergy-1"),
        ]
    ]
    rendered = api._render_grounded_answer(answer, sources, [])

    # Assert: retain conversation context and the allowed read-only behavior.
    assert len(requests) == 2
    assert requests[0]["tool_choice"] == "required"
    system_prompt = requests[0]["input"][0]["content"]
    assert "Never diagnose" in system_prompt
    assert "recommend treatment" in system_prompt
    assert "execute orders" in system_prompt
    assert "write to the chart" in system_prompt
    assert "ask a clarifying question" in system_prompt
    assert "rather than inferring" in system_prompt
    assert [tool["name"] for tool in requests[0]["tools"]] == ["get_patient_chart"]
    assert any(
        message["role"] == "user" and message["content"] == messages[-1].content
        for message in requests[0]["input"]
    )
    assert requests[0]["reasoning"] == {"effort": "low"}
    assert rendered == answer.answer


def test_model_can_clarify_an_ambiguous_chart_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Let the assistant clarify an unclear question instead of guessing."""
    # Arrange: simulate a clarification response after checking chart evidence.
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "function": {
                                    "name": "get_patient_chart",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"answer":"Which chart information would you like me '
                            'to clarify?","citations":[]}'
                        )
                    }
                }
            ]
        },
    ]

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 45.0

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json=responses.pop(0),
                request=httpx.Request("POST", url),
            )

    async def retrieve() -> str:
        return '{"patient_id":"synthetic-patient","sources":[]}'

    _mock_openai(monkeypatch, responses)
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")

    # Act: submit an unclear question.
    answer = asyncio.run(
        api._ask_model(
            [api_models.ChatMessage(role="user", content="What about that?")],
            retrieve,
        )
    )

    # Assert: ask for clarification without inventing chart claims.
    assert answer.answer == "Which chart information would you like me to clarify?"
    assert answer.citations == []


def test_model_rejects_unregistered_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent the assistant from requesting unapproved actions on a patient's chart."""
    # Arrange: simulate a model attempting an unapproved chart action.
    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 45.0

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "tool-1",
                                        "function": {
                                            "name": "write_to_epic",
                                            "arguments": "{}",
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

    async def retrieve() -> str:
        return "{}"

    _mock_openai(
        monkeypatch,
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "function": {
                                        "name": "write_to_epic",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    )
    monkeypatch.setattr(api.settings, "model_name", "synthetic-model")
    monkeypatch.setattr(api.settings, "model_api_key", "synthetic-key")
    monkeypatch.setattr(api.settings, "model_base_url", "https://model.example.test/v1")

    # Act and assert: refuse the unapproved chart action.
    with pytest.raises(ValueError, match="unregistered FHIR tool"):
        asyncio.run(
            api._ask_model(
                [api_models.ChatMessage(role="user", content="Do something")],
                retrieve,
            )
        )
