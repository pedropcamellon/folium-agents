"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  ChatResponse,
  clearSession,
  ConnectionStatus,
  createSession,
  getConnectionStatus,
  getPatientProfile,
  PatientProfile,
  sendMessage,
} from "@/lib/api";

type Turn = {
  question: string;
  result?: ChatResponse;
  error?: string;
};

const ACTIVE_SESSION_STORAGE_KEY = "folium-agents-active-session";
const CONNECTIONS_STORAGE_KEY = "folium-agents-connections";

function savedConnections(): string[] {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(CONNECTIONS_STORAGE_KEY) || "[]");
    return Array.isArray(saved)
      ? saved.filter((id): id is string => typeof id === "string" && /^[A-Za-z0-9_-]{43}$/.test(id)).slice(-12)
      : [];
  } catch {
    return [];
  }
}

function messageFromError(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export default function Chat() {
  const [sessionId, setSessionId] = useState("");
  const [connections, setConnections] = useState<string[]>([]);
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [patientProfile, setPatientProfile] = useState<PatientProfile | null>(null);
  const [patientDetailsUnavailable, setPatientDetailsUnavailable] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [patientId, setPatientId] = useState("");
  const [patientBusy, setPatientBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setConnections(savedConnections());
    const id =
      new URLSearchParams(window.location.search).get("session_id") ||
      window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!id) return;

    setSessionId(id);
    setContextLoading(true);
    getConnectionStatus(id)
      .then((connection) => {
        setStatus(connection);
        setPatientId(connection.patientId);
        window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, id);
        const known = [...new Set([...savedConnections(), id])].slice(-12);
        window.localStorage.setItem(CONNECTIONS_STORAGE_KEY, JSON.stringify(known));
        setConnections(known);
        if (!new URLSearchParams(window.location.search).has("session_id")) {
          window.history.replaceState(
            null,
            "",
            `/?session_id=${encodeURIComponent(id)}`,
          );
        }
        if (connection.connected) {
          void getPatientProfile(id)
            .then(setPatientProfile)
            .catch(() => setPatientDetailsUnavailable(true));
        }
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiRequestError && [401, 404].includes(reason.status)) {
          window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
          const known = savedConnections().filter((candidate) => candidate !== id);
          window.localStorage.setItem(CONNECTIONS_STORAGE_KEY, JSON.stringify(known));
          setConnections(known);
        }
        setSessionId("");
        setStatus(null);
        setError(
          `Could not restore the patient context: ${messageFromError(
            reason,
            "The chat session is unavailable.",
          )} Select the patient again to start a new session.`,
        );
        window.history.replaceState(null, "", "/");
      })
      .finally(() => setContextLoading(false));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, retrieving]);

  async function selectPatient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedPatientId = patientId.trim();
    if (!selectedPatientId || patientBusy) return;

    setPatientBusy(true);
    setError("");
    try {
      if (sessionId) {
        await clearSession(sessionId);
        window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
        setSessionId("");
        setStatus(null);
        setTurns([]);
      }
      const session = await createSession(selectedPatientId);
      window.location.assign(session.authorizationUrl);
    } catch (reason) {
      setError(
        messageFromError(reason, "Could not start the patient session."),
      );
      setPatientBusy(false);
    }
  }

  async function changePatientContext() {
    setError("");
    if (sessionId) {
      try {
        await clearSession(sessionId);
      } catch (reason) {
        setError(
          `Could not end the current session: ${messageFromError(
            reason,
            "The session could not be cleared.",
          )}`,
        );
        return;
      }
    }
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    const known = savedConnections().filter((id) => id !== sessionId);
    window.localStorage.setItem(CONNECTIONS_STORAGE_KEY, JSON.stringify(known));
    setConnections(known);
    setSessionId("");
    setStatus(null);
    setPatientProfile(null);
    setPatientDetailsUnavailable(false);
    setPatientId("");
    setTurns([]);
    setQuestion("");
    window.history.replaceState(null, "", "/");
  }

  function authorizeAnotherPatient() {
    // Keep each independently authorized bearer context; never reuse its token.
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    setSessionId("");
    setStatus(null);
    setPatientProfile(null);
    setPatientDetailsUnavailable(false);
    setPatientId("");
    setTurns([]);
    setQuestion("");
    setError("");
    window.history.replaceState(null, "", "/");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = question.trim();
    if (!prompt || !sessionId || !status?.connected || busy) return;
    setQuestion("");
    setBusy(true);
    setRetrieving(true);
    setError("");
    const index = turns.length;
    setTurns((current) => [...current, { question: prompt }]);
    try {
      const result = await sendMessage(sessionId, prompt);
      setTurns((current) =>
        current.map((turn, turnIndex) =>
          turnIndex === index ? { ...turn, result } : turn,
        ),
      );
    } catch (reason) {
      const message = messageFromError(reason, "The request failed.");
      setTurns((current) =>
        current.map((turn, turnIndex) =>
          turnIndex === index ? { ...turn, error: message } : turn,
        ),
      );
    } finally {
      setRetrieving(false);
      setBusy(false);
    }
  }

  const connected = status?.connected === true;
  const connectionLabel = contextLoading
    ? "Checking connection"
    : connected
      ? "EHR connected"
      : "No patient selected";

  return (
    <div className="ehr-app">
      <header className="ehr-topbar">
        <div className="ehr-brand" aria-label="Folium Agents">
          <span className="brand-mark">F</span>
          <span className="brand-copy">
            <strong>Folium Agents</strong>
            <small>Talk to your EHR</small>
          </span>
        </div>
        <div className="topbar-context">
          <span className="environment-tag">Training environment</span>
          <span>Talk to your EHR</span>
        </div>
        <div className="topbar-user">
          <span className="user-avatar" aria-hidden="true">S</span>
          <span>Demo workspace</span>
        </div>
      </header>
      <nav className="ehr-nav" aria-label="Chart navigation">
        <span className="nav-item">Summary</span>
        <span className="nav-item">Medications</span>
        <span className="nav-item">Conditions</span>
        <span className="nav-item active">Assistant</span>
      </nav>

      <main className="page-content chat-page">
        <section className="patient-banner">
          <div className="patient-avatar" aria-hidden="true">P</div>
          <div className="patient-identity">
            <p className="section-kicker">Patient context</p>
            <h1>
              {connected
                ? patientProfile?.givenName || patientProfile?.familyName
                  ? [patientProfile.givenName, patientProfile.familyName]
                      .filter(Boolean)
                      .join(" ")
                  : `Patient ${status.patientId}`
                : "No patient selected"}
            </h1>
            <span>
              {connected
                ? patientProfile?.birthDate
                  ? `Date of birth: ${patientProfile.birthDate}`
                  : "Synthetic chart · FHIR patient context"
                : "Select a patient in this workspace to begin"}
            </span>
          </div>
          <div className="patient-status" role="status">
            <span className={connected ? "status-dot connected" : "status-dot"} />
            <span className={connected ? "status connected" : "status"}>
              {connectionLabel}
            </span>
          </div>
          {connected && (
            <button
              className="secondary end-session"
              onClick={authorizeAnotherPatient}
              disabled={patientBusy || busy}
            >
              Authorize another patient
            </button>
          )}
        </section>

        <div className="workspace-layout">
          <aside className="panel chart-sidebar">
            <p className="section-kicker">Workspace</p>
            <h2>Patient context</h2>
            {connections.length > 0 && (
              <label>
                Separately authorized connections
                <select
                  aria-label="Switch authorized connection"
                  value={sessionId}
                  disabled={patientBusy || busy || contextLoading}
                  onChange={(event) => {
                    if (event.target.value) {
                      window.location.assign(`/?session_id=${encodeURIComponent(event.target.value)}`);
                    }
                  }}
                >
                  <option value="">Select a connection</option>
                  {connections.map((id, index) => (
                    <option key={id} value={id}>Connection {index + 1}</option>
                  ))}
                </select>
              </label>
            )}
            {connected ? (
              <>
                <div className="context-row">
                  <span>Patient ID</span>
                  <strong>{status.patientId}</strong>
                </div>
                <div className="context-row">
                  <span>Given name</span>
                  <strong>{patientProfile?.givenName ?? "Not available"}</strong>
                </div>
                <div className="context-row">
                  <span>Family name</span>
                  <strong>{patientProfile?.familyName ?? "Not available"}</strong>
                </div>
                <div className="context-row">
                  <span>Date of birth</span>
                  <strong>{patientProfile?.birthDate ?? "Not available"}</strong>
                </div>
                {patientDetailsUnavailable && (
                  <p className="muted" role="status">
                    Patient details are not available for this connection.
                  </p>
                )}
                <div className="context-row">
                  <span>Connection</span>
                  <strong>Authorized</strong>
                </div>
                <div className="context-row">
                  <span>Access</span>
                  <strong>Read only</strong>
                </div>
                <div className="context-row">
                  <span>Session</span>
                  <strong>Connection retained; chat not saved</strong>
                </div>
                <button
                  className="secondary context-action"
                  onClick={changePatientContext}
                  disabled={patientBusy || busy}
                >
                  End session
                </button>
              </>
            ) : contextLoading ? (
              <p className="muted" role="status">Restoring patient context...</p>
            ) : (
              <form className="patient-selector" onSubmit={selectPatient}>
                <label htmlFor="patient-id">Patient FHIR ID</label>
                <input
                  id="patient-id"
                  autoComplete="off"
                  required
                  maxLength={128}
                  value={patientId}
                  onChange={(event) => setPatientId(event.target.value)}
                  placeholder="Enter a synthetic patient ID"
                  aria-describedby="patient-id-help"
                  disabled={patientBusy}
                />
                <p id="patient-id-help" className="field-help">
                  Enter a known synthetic ID. Patient context is never searched
                  or changed automatically.
                </p>
                <button type="submit" disabled={patientBusy || !patientId.trim()}>
                  {patientBusy ? "Connecting..." : "Connect to health record"}
                </button>
              </form>
            )}
            <div className="sidebar-note">
              Chart answers use records available to this authorized session.
              Review the sources attached to each response.
            </div>
          </aside>

          <section className="panel chat-panel">
            <div className="chat-panel-heading">
              <div>
                <p className="section-kicker">Folium Agents</p>
                <h2>Ask about this chart</h2>
              </div>
              <span className="read-only-badge">Read only</span>
            </div>
            {error && <p role="alert" className="error api-error">{error}</p>}
            <section
              className="conversation"
              aria-live="polite"
              aria-label="Conversation"
            >
              {turns.length === 0 && (
                <div className="empty-chat">
                  <span className="empty-chat-icon" aria-hidden="true">?</span>
                  <h3>{connected ? "What would you like to know?" : "Your chat is ready"}</h3>
                  <p className="muted">
                    {connected
                      ? "Ask an open-ended question about the selected patient's chart. Answers include source records."
                      : "Select a patient context in the panel to start a read-only chart conversation."}
                  </p>
                </div>
              )}
              {turns.map((turn, index) => (
                <article className="turn" key={`${index}-${turn.question}`}>
                  <p className="user-message">{turn.question}</p>
                  {turn.result && (
                    <div className="assistant-message">
                      <p>{turn.result.answer}</p>
                      {turn.result.sources.length > 0 && (
                        <details>
                          <summary>Sources ({turn.result.sources.length})</summary>
                          <ul>
                            {turn.result.sources.map((source) => (
                              <li key={`${source.sourceType}/${source.sourceId}`}>
                                <strong>{source.sourceType}/{source.sourceId}</strong>
                                {" — "}{source.title}
                                {source.status && ` · ${source.status}`}
                                {source.date && ` · ${source.date}`}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                      {turn.result.warnings.map((warning) => (
                        <p className="warning" key={warning}>
                          Retrieval warning: {warning}. This response may be incomplete.
                        </p>
                      ))}
                    </div>
                  )}
                  {turn.error && <p role="alert" className="error">{turn.error}</p>}
                </article>
              ))}
              {retrieving && (
                <p className="muted" role="status">
                  Retrieving authorized chart data...
                </p>
              )}
              <div ref={endRef} />
            </section>
            <form className="composer" onSubmit={submit}>
              <label className="sr-only" htmlFor="question">Ask a chart question</label>
              <textarea
                id="question"
                rows={2}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask a question about the chart"
                disabled={!connected || busy}
              />
              <button
                type="submit"
                disabled={!connected || busy || !question.trim()}
              >
                {busy ? "Sending..." : "Send"}
              </button>
            </form>
          </section>
        </div>
        <p className="clinical-disclaimer">
          Synthetic data only. Responses are not a substitute for clinical
          judgment and do not diagnose, recommend treatment, place orders, or
          change the medical record.
        </p>
      </main>
      <footer className="ehr-footer">
        Folium Agents demo · Synthetic data only · Not for clinical use
      </footer>
    </div>
  );
}
