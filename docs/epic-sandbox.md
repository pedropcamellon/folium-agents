# Epic sandbox connector and CLI

The Epic adapter is the first implementation of the provider-neutral EHR
connector contract. It uses SMART on FHIR for read-only synthetic sandbox
access. The CLI's direct Patient lookup uses an explicit FHIR ID. The web
search uses demographics and returns candidates, not an exhaustive roster.

## Configure

Set these variables in the repository-root `.env` file. Keep the private key
outside source control and use the exact callback URI registered for the Epic
sandbox app.

```dotenv
EPIC_CLIENT_ID=your-sandbox-client-id
EPIC_REDIRECT_URI=http://localhost:8765/callback
EPIC_TOKEN_AUTH_METHOD=none
EPIC_SCOPE=openid fhirUser user/Patient.rs
```

The default `none` method sends the client ID and PKCE verifier without a
client secret or private key. Use the authentication method configured for
your Epic app registration. The `patients` command requires Patient read/search. The web chat uses a
separate patient-scoped SMART grant for its registered read-only resources.
Verify those scopes against the Epic app registration and actual sandbox grant
before relying on any resource type. See [Epic chat setup](./epic-chat.md).

Private-key JWT is optional. To use it, upload your public key to the Epic app
registration, then set `EPIC_TOKEN_AUTH_METHOD=private_key_jwt` and
`EPIC_PRIVATE_KEY_PATH` to the corresponding local private key. Set
`EPIC_PRIVATE_KEY_ID` if Epic provides or requires a key ID. Never commit the
private key, passphrase, authorization code, or access token.

## Run

From the repository root:

```bash
uv sync
uv run folium-agents epic discover
uv run folium-agents epic patients --patient-id <FHIR_ID>
```

`epic discover` also reads the FHIR CapabilityStatement at `<FHIR base>/metadata`
to show available resource interactions and Patient search parameters. Epic's
CapabilityStatement is server-wide and does not grant those interactions to the
app; the app registration and token scopes still control access. The CLI
patient command uses a Patient FHIR ID from its
[test patient documentation](https://fhir.epic.com/Documentation?docId=testpatients).
The patient command authorizes through the browser, verifies OAuth state and
PKCE, then searches by that ID. The response may contain the full Patient
resource, but the CLI displays only its ID and name. OAuth tokens are cached
in the OS credential store and are never displayed by the CLI.

The sandbox contains synthetic test data. This does not authorize access to
production systems; each Epic customer controls and approves its own
connection.

## Patient search and scope authorization

The web app starts with a provider-level OAuth2 grant for demographic
Patient.Search (`user/Patient.rs`). Search uses given name, family name, and
date of birth (`YYYY-MM-DD`), sent as the FHIR `given`, `family`, and
`birthdate` parameters without matching modifiers. This matches Epic's
documented default minimum data set; organizations can require additional
demographics. A name-only experiment returned a provider rejection, but the
exact cause remains unconfirmed because the original OperationOutcome code and
severity were not captured. Search results require explicit patient
selection. If a search returns no matches, check the details or access; do not
conclude that no patient exists. This search is not a complete patient roster.
An Epic error or warning OperationOutcome is reported as a rejected search
with guidance to verify configured requirements or Patient.Search app access;
provider diagnostic text is not logged. Rejected OperationOutcomes include
only allowlisted FHIR issue codes and severity values in the API logs.

After selection, the app starts the existing patient-scoped SMART PKCE
authorization for Clinical and Claims. The provider search token is not reused
for patient chart reads. The patient grant includes the clinical
patient-context scopes and `user/ExplanationOfBenefit.rs`; it does not request
wildcard access. Each patient chat remains bound to its selected patient.
Changing patients clears the conversation and starts a new patient
authorization context. Use the same hostname for the app and registered
callback (for example, `localhost`) so the browser can return the session.

Epic's documented search behavior does not prove that the configured app and
clinician have the required provider-level security. Verify the app
registration, user type, organization-specific minimum data set, and live
synthetic search separately. CapabilityStatement metadata and offline tests
are not proof of authorization.

The Epic app must enable the required MedicationRequest, AllergyIntolerance,
Condition, Patient, and ExplanationOfBenefit interactions for the relevant
user types. Epic may return the EOB read and search permissions separately as
`user/ExplanationOfBenefit.r` and `user/ExplanationOfBenefit.s`. The EOB
search uses the shared authorization and validates every returned EOB against
the selected patient. If Epic returns an explicit scope list, it must include
the combined `.rs` permission or both `.r` and `.s`; a missing permission is
reported separately from an expired session or malformed response. When the
requested scopes change, an older saved connection must be reauthorized before
it can be used for Claims.

Epic's current [Claim Search specification](https://fhir.epic.com/Specifications?api=1073)
marks `patient` as required and `created` as optional. Financials sends
`use=claim` and omits `created` to search all available claim dates for that
patient. Omitting `use` also requests prior authorizations, which are outside
this feature's scope and can generate a subtype-specific suppression warning.
Pagination stays on
the same host and resource; an included patient filter must match, and each
EOB on every page must reference the selected patient. Duplicate IDs and
invalid results are rejected, including EOBs whose `use` is not `claim`.
Search stops after 10 pages, 1,000 records, or
60 seconds with an explicit failure instead of accepting partial evidence.
If a limit is reached, the request fails; it never presents a partial list as
complete.

Epic's current [Claim Search specification](https://fhir.epic.com/Specifications?api=1073)
marks `patient` as required and `created` as optional. The app does not
enumerate patients, assume an organization-wide queue, or fall back to local
fixtures. A rejected request reports the upstream HTTP status without exposing
provider diagnostics. Successful results show source, selected patient,
retrieval completeness, pagination, coverage limitations, and EOB amounts
without inventing an outstanding balance.

EOB adjudication is not internal posting evidence. Investigation and posting
preview remain unavailable for Epic records until remittance and internal
posting sources are verified. Chat can summarize returned EOB evidence with
citations and limitations; it cannot post payments or infer internal balances.
The shared chat does not call the legacy synthetic investigation API and never
falls back to its fixtures.

Live diagnosis on 2026-11-15 confirmed that the original suppression warning
was specifically for the unauthorized **Prior Auth** EOB subtype, not Claim.
Adding the documented `use=claim` filter removed that warning without adding
OAuth permissions. The selected patient's claims-only request returned HTTP
200 with code `4101`, Epic's documented no-results outcome.

The app recognizes warning-level `processing` with numeric code `4101` as an
empty completed search only when it is consistent with the bundle total,
contains no claim records, and has no next page. It continues to reject other
warnings, suppression, errors, contradictory totals, and incomplete results.
Chat reports a completed empty claim search without inventing a zero balance
or posting status. This path was verified through the live shared chat after
reauthorization, with zero retrieval warnings and coverage notes displayed
separately. A populated live claim list still requires an authorized
sandbox patient with claim fixtures; clinical records do not imply that such
fixtures exist.

The standalone MedicationRequest review command has been superseded by the
open-flow web chat. Its currently implemented resource coverage is provisional
until actual Epic sandbox interactions and app scopes are confirmed. Offline
tests do not establish sandbox or customer interoperability.
