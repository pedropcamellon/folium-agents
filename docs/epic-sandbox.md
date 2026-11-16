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
EPIC_SCOPE=<configured-sandbox-permissions>
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

`epic discover` also reads the FHIR capability metadata to show available
resource interactions and Patient search parameters. This metadata is
server-wide and does not grant those interactions to the app; the app
registration and permissions still control access. The CLI
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

The web app starts with provider-level access for demographic Patient.Search.
Search uses given name, family name, and date of birth in `YYYY-MM-DD` format,
without unverified matching modifiers. This matches Epic's
documented default minimum data set; organizations can require additional
demographics. A name-only experiment returned a provider rejection, but the
exact cause remains unconfirmed because the original OperationOutcome code and
severity were not captured. Search results require explicit patient
selection. If a search returns no matches, check the details or access; do not
conclude that no patient exists. This search is not a complete patient roster.
Recognized no-match outcomes are shown as empty results. Other Epic errors or
warnings remain explicit failures; internal diagnostics retain only allowlisted
issue categories and severity, not provider text.

After selection, the app starts the existing patient-scoped SMART PKCE
authorization for Clinical and Claims. The provider search token is not reused
for patient chart reads. The patient grant includes the required clinical
patient-context and claims permissions; it does not request wildcard access.
Each patient chat remains bound to its selected patient.
Changing patients clears the conversation and starts a new patient
authorization context. Use the same hostname for the app and registered
callback (for example, `localhost`) so the browser can return the session.

Epic's documented search behavior does not prove that the configured app and
clinician have the required provider-level security. Verify the app
registration, user type, organization-specific minimum data set, and live
synthetic search separately. CapabilityStatement metadata and offline tests
are not proof of authorization.

The Epic app must enable the required clinical and claims interactions for the
relevant user types. Epic may grant claims search and read access separately;
both are required for claims retrieval. The claims search uses the shared
authorization and validates every returned EOB against the selected patient.
If the granted permissions do not include both capabilities, claims access is
reported separately from an expired session or malformed response. When
requested permissions change, an older saved connection must be reauthorized
before it can be used for Claims.

Epic's current [Claim Search specification](https://fhir.epic.com/Specifications?api=1073)
requires a selected patient and makes a creation-date filter optional.
Financials searches claims across all available dates for that patient.
Requests that are not restricted to claims can also return prior
authorizations, which are outside this feature's scope and can generate a
subtype-specific suppression warning. Pagination stays on the same host and
resource; any patient filter must match, and each EOB on every page must
reference the selected patient. Duplicate IDs, invalid results, and
non-claim EOBs are rejected.
Search stops after 10 pages, 1,000 records, or
60 seconds with an explicit failure instead of accepting partial evidence.
If a limit is reached, the request fails; it never presents a partial list as
complete.

Epic's current [Claim Search specification](https://fhir.epic.com/Specifications?api=1073)
requires a selected patient and makes a creation-date filter optional. The app
does not enumerate patients, assume an organization-wide queue, or fall back
to local fixtures. A rejected request reports the upstream HTTP status without
exposing provider diagnostics. Successful results show source, selected
patient, retrieval completeness, pagination, coverage limitations, and EOB
amounts without inventing an outstanding balance.

EOB adjudication is not internal posting evidence. Investigation and posting
preview remain unavailable for Epic records until remittance and internal
posting sources are verified. Chat can summarize returned EOB evidence with
citations and limitations; it cannot post payments or infer internal balances.
The shared chat does not call the legacy synthetic investigation API and never
falls back to its fixtures.

When no claims are available for the selected patient, chat clearly reports
that no matching claims were found. This does not mean the patient has a zero
balance or confirm payment or posting status. If the search fails or results
are incomplete, chat reports that condition instead of presenting an empty
result. Claim availability depends on the records accessible through the
configured Epic sandbox.

The standalone MedicationRequest review command has been superseded by the
open-flow web chat. Its currently implemented resource coverage is provisional
until actual Epic sandbox interactions and app scopes are confirmed. Offline
tests do not establish sandbox or customer interoperability.
