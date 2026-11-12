"""SMART, FHIR, and medication-review models for Epic."""

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TOKEN_EXPIRY_SKEW_SECONDS = 30


class SmartConfiguration(BaseModel):
    authorization_endpoint: str
    token_endpoint: str
    code_challenge_methods_supported: list[str] = Field(default_factory=list)


class CapabilitySearchParameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str | None = None


class CapabilityInteraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str


class CapabilityResource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: str = Field(alias="type")
    interactions: list[CapabilityInteraction] = Field(
        default_factory=list,
        alias="interaction",
    )
    search_parameters: list[CapabilitySearchParameter] = Field(
        default_factory=list,
        alias="searchParam",
    )


class CapabilityRest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resources: list[CapabilityResource] = Field(default_factory=list, alias="resource")


class FhirCapabilityStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["CapabilityStatement"] = Field(alias="resourceType")
    rest: list[CapabilityRest] = Field(default_factory=list)


class EpicToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None
    patient: str | None = None
    encounter: str | None = None


class CachedEpicToken(BaseModel):
    token: EpicToken
    expires_at: float

    @property
    def is_valid(self) -> bool:
        return self.expires_at > time.time() + TOKEN_EXPIRY_SKEW_SECONDS


class CarePlanSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["CarePlan"] = Field(alias="resourceType")
    id: str
    status: str | None = None
    subject: dict[str, Any] | None = None
    encounter: dict[str, Any] | None = None


class EpicPatientName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    family: str = ""
    given: list[str] = Field(default_factory=list)


class EpicPatient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Patient"] = Field(alias="resourceType")
    id: str
    name: list[EpicPatientName] = Field(default_factory=list)
    birth_date: str | None = Field(default=None, alias="birthDate")

    @property
    def primary_name(self) -> EpicPatientName | None:
        return next(
            (patient_name for patient_name in self.name if patient_name.given or patient_name.family),
            None,
        )

    @property
    def display_name(self) -> str:
        patient_name = self.primary_name
        if patient_name is not None:
            parts = [*patient_name.given, patient_name.family]
            display_name = " ".join(part for part in parts if part)
            if display_name:
                return display_name
        return "(name unavailable)"


class PatientBundleEntry(BaseModel):
    resource: EpicPatient


class EpicPatientSearchResult(BaseModel):
    total: int | None = None
    patients: list[EpicPatient]


class EpicPatientBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Bundle"] = Field(alias="resourceType")
    total: int | None = None
    entry: list[PatientBundleEntry] = Field(default_factory=list)


class FhirCoding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system: str | None = None
    code: str | None = None
    display: str | None = None


class FhirCodeableConcept(BaseModel):
    model_config = ConfigDict(extra="ignore")

    coding: list[FhirCoding] | None = Field(default_factory=list)
    text: str | None = None

    @property
    def display(self) -> str:
        if self.text and self.text.strip():
            return self.text.strip()
        for coding in self.coding or []:
            if coding.display and coding.display.strip():
                return coding.display.strip()
            if coding.code and coding.code.strip():
                return coding.code.strip()
        return "Not specified in chart"


class FhirReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reference: str | None = None
    display: str | None = None

    @property
    def resolved_display(self) -> str:
        return self.display or self.reference or "Medication reference unavailable"


class FhirDosageInstruction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str | None = None


class FhirMedicationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["MedicationRequest"] = Field(alias="resourceType")
    id: str
    status: str
    medication_codeable_concept: FhirCodeableConcept | None = Field(
        default=None,
        alias="medicationCodeableConcept",
    )
    medication_reference: FhirReference | None = Field(
        default=None,
        alias="medicationReference",
    )
    authored_on: str | None = Field(default=None, alias="authoredOn")
    dosage_instruction: list[FhirDosageInstruction] | None = Field(
        default_factory=list,
        alias="dosageInstruction",
    )

    @property
    def medication_display(self) -> str:
        if self.medication_codeable_concept:
            return self.medication_codeable_concept.display
        if self.medication_reference:
            return self.medication_reference.resolved_display
        return "Medication unavailable in chart"

    @property
    def medication_code(self) -> tuple[str, str] | None:
        if self.medication_codeable_concept is None:
            return None
        for coding in self.medication_codeable_concept.coding or []:
            if coding.system and coding.code:
                return coding.system, coding.code
        return None

    @property
    def dosage_text(self) -> str | None:
        for dosage in self.dosage_instruction or []:
            if dosage.text and dosage.text.strip():
                return dosage.text.strip()
        return None


class FhirClinicalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["AllergyIntolerance", "Condition"] = Field(
        alias="resourceType"
    )
    id: str
    code: FhirCodeableConcept | None = None
    clinical_status: FhirCodeableConcept | None = Field(
        default=None,
        alias="clinicalStatus",
    )
    verification_status: FhirCodeableConcept | None = Field(
        default=None,
        alias="verificationStatus",
    )
    recorded_date: str | None = Field(default=None, alias="recordedDate")
    onset_date_time: str | None = Field(default=None, alias="onsetDateTime")

    @property
    def display(self) -> str:
        if self.code:
            return self.code.display
        return "Not specified in chart"

    @property
    def clinical_status_display(self) -> str:
        if self.clinical_status:
            return self.clinical_status.display
        return "Not specified"

    @property
    def verification_status_display(self) -> str:
        if self.verification_status:
            return self.verification_status.display
        return "Not specified"


class FhirSearchEntry(BaseModel):
    resource: dict[str, Any]


class FhirSearchLink(BaseModel):
    relation: str
    url: str


class FhirSearchBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["Bundle"] = Field(alias="resourceType")
    bundle_type: str | None = Field(default=None, alias="type")
    total: int | None = None
    link: list[FhirSearchLink] = Field(default_factory=list)
    entry: list[FhirSearchEntry] = Field(default_factory=list)


class FhirOperationIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: Literal["fatal", "error", "warning", "information", "success"]
    code: str


class FhirOperationOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_type: Literal["OperationOutcome"] = Field(alias="resourceType")
    issue: list[FhirOperationIssue]


class FhirResourceSearchResult(BaseModel):
    resources: list[dict[str, Any]]
    outcome_notes: list[str]


class MedicationEntrySummary(BaseModel):
    resource_id: str
    display: str
    status: str
    authored_on: str | None = None
    dosage_text: str | None = None
    code_system: str | None = None
    code: str | None = None


class ClinicalRecordSummary(BaseModel):
    resource_id: str
    display: str
    clinical_status: str
    verification_status: str
    date: str | None = None


class PossibleDuplicateMedication(BaseModel):
    display: str
    code_system: str
    code: str
    resource_ids: list[str]
    review_note: str = (
        "Possible duplicate active medication entries; verify with a clinician."
    )


class EpicMedicationSafetyReview(BaseModel):
    patient_id: str
    active_medications: list[MedicationEntrySummary]
    allergies: list[ClinicalRecordSummary]
    conditions: list[ClinicalRecordSummary]
    possible_duplicate_medications: list[PossibleDuplicateMedication]
    outcome_notes: list[str] = Field(default_factory=list)
