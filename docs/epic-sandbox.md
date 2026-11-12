# Epic sandbox connector and CLI

The Epic adapter is the first implementation of the provider-neutral EHR
connector contract. It uses SMART on FHIR for read-only synthetic sandbox
access. Patient lookup requires an explicit FHIR ID; it does not enumerate
patients.

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

The standalone MedicationRequest review command has been superseded by the
open-flow web chat. Its currently implemented resource coverage is provisional
until actual Epic sandbox interactions and app scopes are confirmed. Offline
tests do not establish sandbox or customer interoperability.
