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
  sessionId: string;
};

export type ConnectionStatus = {
  connected: boolean;
  patientId: string;
};

export type PatientProfile = {
  patientId: string;
  givenName: string | null;
  familyName: string | null;
  birthDate: string | null;
};

export class ApiRequestError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiRequestError";
  }
}

const configuredApiBaseUrl = process.env.NEXT_PUBLIC_FOLIUM_AGENTS_API_URL?.trim();

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  const operation =
    path.endsWith("/chat") ? "chat" :
    path.endsWith("/patient") ? "patient" :
    init?.method === "DELETE" ? "disconnect" :
    init?.method === "POST" ? "authorize" : "restore";
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
      console.error("api.network_failed", { operation, errorType: "TypeError" });
      throw new Error(
        `Cannot reach the Folium Agents API at ${apiBaseUrl}. ` +
          "Start the API service and open the app on localhost or 127.0.0.1.",
      );
    }
    throw reason;
  }
  if (!response.ok) {
    const rawId = response.headers.get("X-Correlation-ID");
    const correlationId = rawId && /^[a-f0-9]{32}$/.test(rawId) ? rawId : undefined;
    console.error("api.request_failed", {
      operation,
      status: response.status,
      correlationId,
    });
    if (response.status >= 500) {
      throw new ApiRequestError(
        "The chart assistant could not complete this request. Please try again later." +
          (correlationId ? ` Reference: ${correlationId}.` : ""),
        response.status,
      );
    }
    const body = (await response.json().catch(() => null)) as
      | { detail?: unknown }
      | null;
    throw new ApiRequestError(
      (typeof body?.detail === "string" ? body.detail : `API request failed (${response.status}).`) +
        (correlationId ? ` Reference: ${correlationId}.` : ""),
      response.status,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function createSession(patientId: string) {
  return request<{
    sessionId: string;
    patientId: string;
    authorizationUrl: string;
  }>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ patientId }),
  });
}

export function getConnectionStatus(sessionId: string) {
  return request<ConnectionStatus>(`/api/sessions/${encodeURIComponent(sessionId)}`);
}

export function getPatientProfile(sessionId: string) {
  return request<PatientProfile>(
    `/api/sessions/${encodeURIComponent(sessionId)}/patient`,
  );
}

export function sendMessage(sessionId: string, question: string) {
  return request<ChatResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/chat`,
    {
      method: "POST",
      body: JSON.stringify({ question }),
    },
  );
}

export function clearSession(sessionId: string) {
  return request<void>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}
