---
name: epic-ehr
description: Build, debug, and validate Folium Agents integrations with Epic SMART on FHIR. Use for Epic authorization, scopes, patient context, Clinical reads, ExplanationOfBenefit claims, OperationOutcome warnings, sandbox fixtures, and live integration proof.
---

# Epic integration

Deliver verified, patient-bound reads before expanding features or permissions.
This project uses its own SMART/FHIR client and connector; do not assume a
separate Epic SDK exists or provides a capability.

## Start here

1. Read the active task and the owning connector code.
2. Read [sandbox behavior and proof](../../../docs/epic-sandbox.md) and
   [chat setup](../../../docs/epic-chat.md).
3. Check the exact Epic API specification, including user types, resource
   subtypes, required filters, optional filters, and warning semantics.
4. Separate documented behavior, implemented behavior, and live verification.
   Capability metadata, granted scopes, HTTP 200, and passing offline tests
   are not interchangeable evidence.

## Authorization and patient context

- Add only the explicit read/search permissions required by approved features.
  Do not request wildcard access or add unrelated resources to fix a warning.
- App registration must enable the relevant API interactions and OAuth user
  types. A token grant alone does not establish access to every resource subtype.
- Reuse the server-held patient session for Clinical and Financials. Tools
  must not accept a model-supplied patient override.
- Validate the OAuth token patient against the selected patient. Validate every
  returned EOB patient reference, on every page, against the same context.
- Distinguish scopes requested, permissions granted, and data actually returned.
  Report Clinical and Claims permission sets independently when displaying access.
- The claims request uses SMART v2 `user/ExplanationOfBenefit.rs`. Epic can
  return separate `.r` and `.s` tokens; require both. The current connector also
  accepts the equivalent legacy `user/ExplanationOfBenefit.read` grant.
- An omitted returned scope is unconfirmed, not proof of denial or permission.
  During refresh, preserve the previous grant if the response omits scope.
- Requested-scope changes invalidate the saved connection binding. Reauthorize;
  do not reuse an old token as if it acquired the new permissions.
- Tokens stay server-side. Complete login and consent through the browser;
  never ask users to paste credentials, tokens, or authorization codes.
- Use a consistent hostname for the app and registered callback.
- Do not equate selecting a patient with obtaining new OAuth consent. The
  existing chat uses a patient-bound connection; a provider workspace should
  first verify whether clinician/admin user-level grants permit patient switching
  through one connection. Keep server-side patient isolation regardless, and
  never reuse a patient-restricted grant for another patient. Backend/system
  authorization is a separate approved integration, not an admin shortcut.

## Claims: the important request distinction

For the implemented patient claim workflow:

```http
GET {issuer}/ExplanationOfBenefit?patient={selected-patient}&use=claim&_count=100
Accept: application/fhir+json
```

- `patient` is required. `created` is optional: omit it for all available dates.
  Do not invent a date window or describe local retrieval caps as Epic limits.
- Always send `use=claim`. Omitting `use` searches both claims and prior
  authorizations. A Prior Auth permission warning does not prove Claim access
  is missing. Do not solve this by requesting Prior Auth permissions.
- Require returned EOBs to declare `use=claim`; reject another subtype.
- Pagination must remain on the expected server and resource. Reject changed
  patient or `use` filters. Opaque page links still require per-record validation.
- Reject duplicate IDs, malformed resources, contradictory totals, unsafe links,
  and incomplete retrieval. Never label partial results complete.
- The current implementation caps retrieval at 10 pages, 1,000 records, and
  60 seconds. Check the code before changing or documenting those local caps.
- EOB Claim data describes health-plan claims. It is not automatically a provider
  billing ledger, remittance feed, internal posting record, or outstanding balance.

## Interpret OperationOutcome before changing permissions

A successful HTTP response can contain OperationOutcome entries instead of,
or alongside, EOBs. Parse the discriminated resource types; do not assume
every Bundle entry is an ExplanationOfBenefit.

1. Inspect severity, standard issue code, numeric Epic code, and the affected
   subtype. Read explanatory text only with credentials and identifiers redacted.
2. Distinguish malformed data, unsupported subtypes, authorization failure,
   missing fixtures, normal no-results, and incomplete coverage.
3. Never ignore suppression or warning-level outcomes globally.

Verified examples:

- `59205` / `suppressed` identified an unauthorized **Prior Auth** subtype when
  `use` was omitted. The documented `use=claim` filter removed that warning.
  Numeric codes alone are not a substitute for checking the subtype explanation.
- `4101` means the request returned no results. The claims implementation accepts
  warning-level `processing` with this numeric code as a completed empty search
  only if there are no claim records, no next page, and no contradictory total.
  Other warnings or errors still fail explicitly.
- Zero returned claims are not a zero balance or proof that no claims exist
  outside the selected patient's grant.
- Keep coverage limitations separate from retrieval warnings. A successful empty
  search must not be presented as an access failure or an incomplete request.

## Sandbox proof and debugging

- Use only authorized synthetic sandbox records. Do not enumerate patients or
  silently switch the selected patient to find a populated response.
- Clinical fixtures do not imply claim fixtures. Public examples and sample
  response bodies are not proof that the same records exist in the live sandbox.
- Before concluding that support must supply a fixture, inspect the Claim Search
  specification's sample request and returned EOB patient reference for a
  documented candidate. Treat it as unverified until authorized live retrieval.
  An EOB resource ID in a Read example is not a Patient FHIR ID; a Prior Auth
  example is not Claim evidence.
- Reproduce with the exact patient-bound request and minimum supported filters.
  Inspect sanitized schema errors and outcome classifications before editing.
- If a token expired, obtain fresh browser authorization. Never replay callback
  codes or bypass consent.
- Record request shape, status, completeness, and failure classification without
  retaining patient IDs, names, credentials, raw records, or callback material.
- A live empty search verifies authorization/request handling and the empty path,
  not populated EOB mapping or production interoperability.
- The verified claims-only live path returned no matching records. Populated live
  claim proof remains separate; never replace missing Epic evidence with fixtures.

## Owning code and validation

- [SMART scopes and HTTP client](../../../src/folium_agents/epic/epic.py)
- [Session binding and token refresh](../../../src/folium_agents/epic/adapter.py)
- [Claim contracts, filtering, and outcomes](../../../src/folium_agents/epic/financial_reads.py)
- [Shared FHIR models](../../../src/folium_agents/epic/models.py)
- [Chat tools and response validation](../../../src/folium_agents/api/app.py)
- [Connection and claims tests](../../../tests/modules/epic/test_connections.py)
- [Chat tool and grounding tests](../../../tests/modules/epic/test_api.py)

Use focused Ruff and ty checks for changed Python files. Run the relevant tests
at final validation, including clinical regressions when shared chat or OAuth
changes. Check frontend lint/types when API or UI contracts change. Test the
specific bug and failure boundaries, not only a happy-path mock.

## Keep this skill current

After Epic work, update this skill when a verified finding changes the reusable
guidance. Update the linked user docs and task evidence where relevant.
Replace outdated guidance instead of accumulating contradictory appendices.
Label unverified hypotheses explicitly; do not turn one fixture's behavior into
a universal Epic rule. Keep run-specific logs, IDs, secrets, and test counts out
of this skill. No autonomous financial or clinical action is authorized here.

Public references:

- [Epic Claim Search specification](https://fhir.epic.com/Specifications?api=1073)
- [Epic sandbox test data](https://fhir.epic.com/Documentation?docId=testpatients)

Last reviewed: 2026-11-15.
