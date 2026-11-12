import json
import logging

import pytest

from folium_agents.core.diagnostics import diagnostic


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            (
                "The model returned chart evidence without citing a source; "
                "no answer was produced."
            ),
            "citations_missing",
        ),
        (
            "Authorized Epic patient did not match selected context.",
            "oauth_patient_mismatch",
        ),
    ],
)
def test_known_failures_log_safe_codes(
    caplog: pytest.LogCaptureFixture, message: str, code: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        diagnostic("chat.model_or_validation_failed", error=ValueError(message))

    fields = json.loads(caplog.records[-1].message)
    assert fields["failure_code"] == code
    assert fields["error_type"] == "ValueError"
    assert message not in caplog.text


def test_unknown_failure_text_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_text = "synthetic-token-and-chart-content"
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        diagnostic("chat.model_or_validation_failed", error=ValueError(sensitive_text))

    fields = json.loads(caplog.records[-1].message)
    assert "failure_code" not in fields
    assert fields["error_type"] == "ValueError"
    assert sensitive_text not in caplog.text
