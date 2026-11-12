"""Allowlisted diagnostic fields; provider exception text is never logged."""

import json
import logging
from contextvars import ContextVar

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="background")
logger = logging.getLogger("uvicorn.error")

_SAFE_FAILURE_CODES = {
    "The model cited a record that was not returned by the active "
    "patient search; no answer was produced.": "citation_not_in_evidence",
    "The model returned chart evidence without citing a source; "
    "no answer was produced.": "citations_missing",
    "The configured model answered without retrieving chart evidence.": "chart_not_retrieved",
    "The configured model returned an empty answer.": "model_answer_empty",
    "The configured model returned an invalid grounded-answer "
    "shape; no answer was produced.": "model_answer_invalid",
    "The model requested too many chart tool calls.": "tool_call_limit",
    "The model requested an unregistered FHIR tool.": "tool_not_registered",
    "The registered FHIR tool accepts no arguments.": "tool_arguments_invalid",
    "The configured model returned a tool call without an ID.": "tool_call_id_missing",
    "The model exceeded the maximum number of chart-tool rounds.": "tool_round_limit",
    "Retrieved chart evidence exceeded the model input limit; "
    "no answer was generated.": "chart_input_limit",
    "OAuth state mismatch; refusing token exchange.": "oauth_state_mismatch",
    "Authorized Epic patient did not match selected context.": "oauth_patient_mismatch",
    "Epic returned a token without a valid lifetime.": "oauth_token_lifetime_invalid",
}


def diagnostic(
    event: str, *, error: Exception | None = None, status: int | None = None
) -> None:
    fields = {"event": event, "correlation_id": correlation_id.get()}
    if error is not None:
        fields["error_type"] = type(error).__name__
        failure_code = _SAFE_FAILURE_CODES.get(str(error))
        if failure_code is not None:
            fields["failure_code"] = failure_code
        response = getattr(error, "response", None)
        if response is not None:
            status = getattr(response, "status_code", status)
    if status is not None:
        fields["status"] = status
    level = (
        logging.WARNING
        if error is not None or (status and status >= 400)
        else logging.INFO
    )
    logger.log(level, json.dumps(fields))
