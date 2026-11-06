# Folium Agents — Epic sandbox connector

This learning project tests an external, clinician-authorized connection to
Epic's FHIR sandbox. The current proof requests a bounded list of synthetic
sample patients using read-only `Patient` access. It does not write records or
print access tokens.

## Configure

Put these settings in the repository-root `.env` file. Keep the private key
outside source control and use the exact callback URI registered for the Epic
sandbox app.

```dotenv
EPIC_CLIENT_ID=your-sandbox-client-id
EPIC_REDIRECT_URI=http://localhost:8765/callback
EPIC_PRIVATE_KEY_PATH=/absolute/path/to/epic-private-key.pem
EPIC_PRIVATE_KEY_ID=your-uploaded-key-id
EPIC_TOKEN_AUTH_METHOD=private_key_jwt
EPIC_SCOPE=openid fhirUser user/Patient.rs
```

For an encrypted PEM, also set `EPIC_PRIVATE_KEY_PASSPHRASE`. `EPIC_FHIR_ISSUER`
defaults to Epic's public R4 sandbox. The app registration must have the
Patient read/search API enabled and the matching public key uploaded. Never
commit the private key, passphrase, authorization code, or access token.

## Run

From the repository root, run:

```bash
uv sync
uv run folium-agents --limit 10
```

The CLI discovers Epic's SMART endpoints, opens the authorization URL in a
browser, receives the response at the registered localhost callback, verifies
OAuth state and PKCE, exchanges the code using a short-lived private-key JWT
client assertion, and requests a maximum of 20 Patient IDs and names. The
bearer token is held in memory and is not displayed.

The sandbox contains synthetic test data. This does not authorize access to
production systems; each Epic customer controls and approves its own
connection.
