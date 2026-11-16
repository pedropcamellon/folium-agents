"""Provider-neutral contracts for patient-bound financial evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ClaimAmount(Contract):
    category: str
    value: str
    currency: str | None


class ClaimEvidence(Contract):
    claim_id: str
    status: str
    created: str
    source_id: str
    amounts: list[ClaimAmount]
    posting_status: Literal["unknown"] = "unknown"


class ClaimSearch(Contract):
    source: str
    patient_id: str
    claims: list[ClaimEvidence]
    pages: int
    complete: bool
    limitations: list[str]


class ClaimSearchError(ValueError):
    """A provider could not return validated financial evidence."""


class ClaimAuthorizationExpired(ClaimSearchError):
    """The provider authorization must be re-established before a read."""
