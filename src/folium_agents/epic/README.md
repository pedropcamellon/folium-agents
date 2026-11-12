# Epic sandbox connector

The Epic module provides the first EHR connector for the provider-neutral
Folium Agents chat. Its web login uses SMART authorization code + PKCE and
keeps tokens server-side. The first chat proof is restricted to synthetic
sandbox patients and read-only resources.

## Configure

Put these settings in the repository-root `.env` file. Keep the private key
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
your Epic app registration. The app must have Patient read/search enabled.

CLI OAuth tokens are stored in the operating system credential store (macOS
Keychain on macOS), not in `.env` or a project file. The CLI reuses an
unexpired access token. If Epic returns a refresh token, it is stored and used
to refresh the access token; otherwise, the CLI asks you to authorize again
after the access token expires. No `offline_access` scope is added
automatically. Remove the saved token with `uv run folium-agents epic logout`.
The web API uses a separate per-connection encrypted store in Compose, not the
host keyring. See the chat guide for restart retention and local revocation.

To opt into `private_key_jwt`, create a key pair and upload only its public key
to the Epic app registration. Keep the private key local and outside the
repository:

```bash
mkdir -p "$HOME/.config/folium-agents/epic"
openssl genrsa -out "$HOME/.config/folium-agents/epic/private.pem" 2048
openssl rsa -in "$HOME/.config/folium-agents/epic/private.pem" -pubout -out "$HOME/.config/folium-agents/epic/public.pem"
chmod 600 "$HOME/.config/folium-agents/epic/private.pem"
```

Set `EPIC_TOKEN_AUTH_METHOD=private_key_jwt` and
`EPIC_PRIVATE_KEY_PATH=/absolute/path/to/private.pem`. If Epic provides or
requires a key ID, set `EPIC_PRIVATE_KEY_ID`; encrypted PEMs also require
`EPIC_PRIVATE_KEY_PASSPHRASE`. See Epic's
[key-pair instructions](https://fhir.epic.com/Documentation?docId=oauth2&section=Creating-Key-Pair).
Never commit the private key, passphrase, authorization code, or access token.

## Run

From the repository root, run:

```bash
uv sync
uv run folium-agents epic discover
uv run folium-agents epic patients --patient-id <FHIR_ID>
```

`epic discover` checks the SMART endpoints and retrieves the FHIR
CapabilityStatement from `<FHIR base>/metadata`, including supported resource
interactions and Patient search parameters. These are server-wide capabilities,
not proof that your app registration has permission to use every interaction.
The patient command opens Epic's
authorization page in your browser. Sign in there using sandbox test-user
credentials and approve the requested access. The CLI then verifies OAuth
state and PKCE, exchanges the code, and searches by the supplied Patient FHIR
ID. The API response may include the full Patient resource because this
sandbox rejects `_elements`; the CLI only displays the ID and name. Tokens are
never displayed by the CLI.

Use an ID listed in Epic's [sandbox test patient documentation](https://fhir.epic.com/Documentation?docId=testpatients).
The patient command never enumerates patients. The web chat flow, Compose
callback URI, actual resource access, and Azure model setup are documented in
[docs/epic-chat.md](../../docs/epic-chat.md).

The sandbox contains synthetic test data. This does not authorize access to
production systems; each Epic customer controls and approves its own
connection. See Epic's [test patient documentation](https://fhir.epic.com/Documentation?docId=testpatients)
for details on the sandbox patients and how to use them.
