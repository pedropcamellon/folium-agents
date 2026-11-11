# OpenEMR demo client

The OpenEMR client provides read-only FHIR R4 capability discovery and bounded
Patient ID search against an authorized OpenEMR instance. The public demo
metadata endpoint can be checked without patient access. Patient search needs
an authorized test account and an OAuth client configured for FHIR
Patient read/search. The harness CLI module is maintained on the `feat/oemr`
branch and is not registered in this branch.

Configure the approved test credentials in environment variables or the
repository-root `.env` file:

```dotenv
OPENEMR_USERNAME=your-openemr-user
OPENEMR_PASSWORD=your-openemr-password
OPENEMR_CLIENT_ID=your-registered-client-id
OPENEMR_CLIENT_SECRET=your-client-secret
```

An authorized pre-issued token can be supplied as `OPENEMR_ACCESS_TOKEN`
instead. For another OpenEMR deployment, set `OPENEMR_FHIR_BASE_URL` and
`OPENEMR_OAUTH_TOKEN_URL`. Do not commit credentials.

On the `feat/oemr` branch, run the module commands from the repository root:

```bash
uv run folium-agents openemr check
uv run folium-agents openemr patients --limit 20
```

Patient search returns IDs only and is limited to 100 results per request.
The password grant is used only for this demo-oriented connector and should
not be assumed appropriate for production deployments. Use only approved
synthetic/test accounts; the shared demo may be reset.
