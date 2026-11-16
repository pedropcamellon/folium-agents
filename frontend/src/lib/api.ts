import type { PatientClaimSearch } from "@/lib/financial-models";

export type ChatSource = {
  sourceType: string;
  sourceId: string;
  title: string;
  date: string | null;
  status: string | null;
};

export type ChatResponse = {
  answer: string;
  sources: ChatSource[];
  warnings: string[];
  limitations: string[];
  sessionId: string;
};

export type ConnectionStatus = {
  connected: boolean;
  patientId: string;
  authorizationState: "authorized" | "authorization_required";
  supportedOperations: ("patient_search" | "patient_chat" | "claims")[];
};

export type EHRProviderInfo = {
  providerId: string;
  supportedOperations: ("patient_search" | "patient_chat" | "claims")[];
};

export type PatientProfile = {
  patientId: string;
  givenName: string | null;
  familyName: string | null;
  birthDate: string | null;
};

export type PatientSearchCandidate = {
  patientId: string;
  givenName: string | null;
  familyName: string | null;
  birthDate: string | null;
};

export type PatientSearchResponse = {
  candidates: PatientSearchCandidate[];
  total: number | null;
  moreMatchesAvailable: boolean;
};

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

const configuredApiBaseUrl =
  process.env.NEXT_PUBLIC_FOLIUM_AGENTS_API_URL?.trim();

if (!configuredApiBaseUrl && typeof window !== "undefined") {
  console.error(
    "NEXT_PUBLIC_FOLIUM_AGENTS_API_URL is not set; using the page hostname for the API.",
  );
}

function getBrowserHostname(): string {
  return window.location.hostname === "0.0.0.0"
    ? "localhost"
    : window.location.hostname;
}

function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    const internalApiBaseUrl =
      process.env.FOLIUM_AGENTS_INTERNAL_API_URL?.trim();
    if (internalApiBaseUrl) {
      return internalApiBaseUrl.replace(/\/$/, "");
    }
  }
  if (configuredApiBaseUrl) {
    const apiBaseUrl =
      typeof window === "undefined"
        ? configuredApiBaseUrl
        : configuredApiBaseUrl.replace(
            /^(https?:\/\/)0\.0\.0\.0(?=[:/]|$)/i,
            (_, protocol: string) => `${protocol}${getBrowserHostname()}`,
          );
    return apiBaseUrl.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${getBrowserHostname()}:8000`;
  }
  throw new Error(
    "The API URL is not configured. Set NEXT_PUBLIC_FOLIUM_AGENTS_API_URL.",
  );
}

type ApiOperation =
  | "list_providers"
  | "chat"
  | "patient"
  | "disconnect"
  | "authorize_patient_search"
  | "search_patients"
  | "disconnect_patient_search"
  | "authorize"
  | "restore"
  | "search_patient_claims"
  | "list_financial_claims"
  | "investigate_claim";

async function request<T>(
  operation: ApiOperation,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch (reason) {
    if (reason instanceof TypeError) {
      console.error("api.network_failed", {
        operation,
        errorType: "TypeError",
      });
      throw new Error(
        `Cannot reach the Folium Agents API at ${apiBaseUrl}. ` +
          "Start the API service and open the app on localhost or 127.0.0.1.",
      );
    }
    throw reason;
  }
  if (!response.ok) {
    const rawId = response.headers.get("X-Correlation-ID");
    const correlationId =
      rawId && /^[a-f0-9]{32}$/.test(rawId) ? rawId : undefined;
    console.error("api.request_failed", {
      operation,
      status: response.status,
      correlationId,
    });
    if (response.status >= 500) {
      throw new ApiRequestError(
        "The assistant could not complete this request. Please try again later." +
          (correlationId ? ` Reference: ${correlationId}.` : ""),
        response.status,
      );
    }

    const body = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new ApiRequestError(
      (typeof body?.detail === "string"
        ? body.detail
        : `API request failed (${response.status}).`) +
        (correlationId ? ` Reference: ${correlationId}.` : ""),
      response.status,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listEHRProviders() {
  return request<EHRProviderInfo[]>("list_providers", "/api/providers");
}

export type FinancialClaim = {
  claimId: string;
  workspaceId: string;
  synthetic: boolean;
  status: string;
  currency: string;
  billedCents: number;
  outstandingCents: number;
};

export type FinancialRun = {
  runId: string;
  workspaceId: string;
  claimId: string;
  status: "completed" | "incomplete" | "failed";
  action: string;
  humanReviewRequired: boolean;
  evidence: Record<string, unknown>;
  preview: Record<string, unknown> | null;
  citations: string[];
  trace: {
    tool: string;
    outcome: "ok" | "failed";
    sourceIds: string[];
    durationMs: number;
  }[];
  error: string | null;
  uncertainties: string[];
};

export function listFinancialClaims() {
  return request<FinancialClaim[]>(
    "list_financial_claims",
    "/api/financial/claims",
  );
}

export function searchPatientClaims(sessionId: string) {
  return request<PatientClaimSearch>(
    "search_patient_claims",
    `/api/sessions/${encodeURIComponent(sessionId)}/financial/claims`,
  );
}

export function investigateClaim(claimId: string) {
  return request<FinancialRun>(
    "investigate_claim",
    `/api/financial/claims/${encodeURIComponent(claimId)}/investigate`,
    { method: "POST" },
  );
}

export async function createSession(patientId: string) {
  return request<{
    sessionId: string;
    patientId: string;
    authorizationUrl: string;
  }>("authorize", "/api/sessions", {
    method: "POST",
    body: JSON.stringify({ patientId }),
  });
}

export function createPatientSearchSession() {
  return request<{
    sessionId: string;
    authorizationUrl: string;
  }>("authorize_patient_search", "/api/patient-search/sessions", {
    method: "POST",
  });
}

export function searchPatients(
  sessionId: string,
  criteria: {
    givenName: string;
    familyName: string;
    birthDate: string;
  },
) {
  return request<PatientSearchResponse>(
    "search_patients",
    `/api/patient-search/sessions/${encodeURIComponent(sessionId)}/search`,
    {
      method: "POST",
      body: JSON.stringify(criteria),
    },
  );
}

export function clearPatientSearchSession(sessionId: string) {
  return request<void>(
    "disconnect_patient_search",
    `/api/patient-search/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

export function getConnectionStatus(sessionId: string) {
  return request<ConnectionStatus>(
    "restore",
    `/api/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function getPatientProfile(sessionId: string) {
  return request<PatientProfile>(
    "patient",
    `/api/sessions/${encodeURIComponent(sessionId)}/patient`,
  );
}

export function sendMessage(sessionId: string, question: string) {
  return request<ChatResponse>(
    "chat",
    `/api/sessions/${encodeURIComponent(sessionId)}/chat`,
    {
      method: "POST",
      body: JSON.stringify({ question }),
    },
  );
}

export function clearSession(sessionId: string) {
  return request<void>(
    "disconnect",
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}
