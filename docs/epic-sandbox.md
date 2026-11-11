# Epic sandbox connector

The Epic adapter is the first external EHR connector proof. It uses SMART on
FHIR authorization for read-only access to synthetic sandbox data. Patient
search requires an explicit FHIR ID; the adapter does not enumerate patients.
The medication review is a chart-evidence summary, not a prediction or
treatment recommendation.

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
your Epic app registration. The `patients` command requires Patient
read/search. The `medication-review` command separately requests these
patient-scoped SMART permissions:

```text
launch/patient patient/MedicationRequest.rs patient/AllergyIntolerance.rs patient/Condition.rs
```

The Epic app registration must enable these scopes and the standalone patient
selection workflow. The command verifies that the Patient FHIR ID selected in
the authorization flow matches `--patient-id` before requesting chart data.
It refuses to produce a report if the context does not match.

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
uv run folium-agents epic medication-review --patient-id <FHIR_ID>
```

`epic discover` also reads the FHIR CapabilityStatement at `<FHIR base>/metadata`
to show available resource interactions and Patient search parameters. Epic's
CapabilityStatement is server-wide and does not grant those interactions to the
app; the app registration and token scopes still control access. The sandbox
rejects unfiltered Patient searches and `_elements`; use a Patient FHIR
ID from its [test patient documentation](https://fhir.epic.com/Documentation?docId=testpatients).
The patient command authorizes through the browser, verifies OAuth state and
PKCE, then searches by that ID. The response may contain the full Patient
resource, but the CLI displays only its ID and name. OAuth tokens are cached
in the OS credential store and are never displayed by the CLI.

The sandbox contains synthetic test data. This does not authorize access to
production systems; each Epic customer controls and approves its own
connection.

## Medication review limits

The medication review retrieves up to 100 patient-scoped `MedicationRequest`,
`AllergyIntolerance`, and `Condition` entries and fails rather than presenting
truncated results. It summarizes charted entries and flags only multiple
active medication requests with the exact same coding system and code as
possible duplicate records. The flag includes source resource IDs and requires
clinician review; it does not establish a duplicate prescription or clinical
risk. The command does not infer allergies, conditions, contraindications,
drug interactions, or treatment changes. An empty result means no matching
resource was returned, not that the patient has no such history. FHIR
OperationOutcome warning codes are displayed without their diagnostic text;
warnings can indicate omitted records, so the review may be incomplete.

The required app-registration scopes and standalone selection behavior have
not yet been verified against a live Epic sandbox launch. Offline tests do not
establish sandbox or customer interoperability.
