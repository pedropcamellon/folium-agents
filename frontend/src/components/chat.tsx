"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  ChatResponse,
  clearSession,
  clearPatientSearchSession,
  ConnectionStatus,
  createSession,
  createPatientSearchSession,
  getConnectionStatus,
  getPatientProfile,
  PatientProfile,
  PatientSearchCandidate,
  PatientSearchResponse,
  searchPatients,
  sendMessage,
} from "@/lib/api";
import PatientSearch from "@/components/patient-search";
import { Button } from "@/components/ui/button";

type Turn = {
  question: string;
  result?: ChatResponse;
  error?: string;
};

const ACTIVE_SESSION_STORAGE_KEY = "folium-agents-active-session";
const ACTIVE_PATIENT_SEARCH_STORAGE_KEY =
  "folium-agents-patient-search-session";

function messageFromError(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export default function Chat() {
  const [view, setView] = useState<"search" | "chat">("search");
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [patientProfile, setPatientProfile] = useState<PatientProfile | null>(
    null,
  );
  const [patientDetailsUnavailable, setPatientDetailsUnavailable] =
    useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [patientBusy, setPatientBusy] = useState(false);
  const [patientSearchSessionId, setPatientSearchSessionId] = useState("");
  const [searchGivenName, setSearchGivenName] = useState("");
  const [searchFamilyName, setSearchFamilyName] = useState("");
  const [searchBirthDate, setSearchBirthDate] = useState("");
  const [searchResult, setSearchResult] =
    useState<PatientSearchResponse | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchConnecting, setSearchConnecting] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const contextVersion = useRef(0);
  const searchVersion = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const searchErrorCode = params.get("patient_search_error");
    if (searchErrorCode) {
      setView("search");
      setSessionId(
        window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY) || "",
      );
      setSearchError(
        searchErrorCode === "authorization_denied"
          ? "Epic authorization was denied. Connect again to search."
          : "Epic patient-search authorization failed. Connect again to search.",
      );
      window.history.replaceState(null, "", "/");
      return;
    }

    const searchId =
      params.get("patient_search_session_id") ||
      window.localStorage.getItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
    if (searchId) {
      setPatientSearchSessionId(searchId);
      setSessionId(
        window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY) || "",
      );
      window.localStorage.setItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY, searchId);
      setView("search");
      window.history.replaceState(null, "", "/");
      return;
    }

    const id =
      params.get("session_id") ||
      window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!id) return;

    const version = contextVersion.current;
    setView("chat");
    setSessionId(id);
    setContextLoading(true);
    getConnectionStatus(id)
      .then((connection) => {
        if (version !== contextVersion.current) return;
        setStatus(connection);
        window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, id);
        if (!new URLSearchParams(window.location.search).has("session_id")) {
          window.history.replaceState(
            null,
            "",
            `/?session_id=${encodeURIComponent(id)}`,
          );
        }
        if (connection.connected) {
          void getPatientProfile(id)
            .then((profile) => {
              if (version === contextVersion.current)
                setPatientProfile(profile);
            })
            .catch(() => {
              if (version === contextVersion.current)
                setPatientDetailsUnavailable(true);
            });
        }
      })
      .catch((reason: unknown) => {
        if (version !== contextVersion.current) return;
        if (
          reason instanceof ApiRequestError &&
          [401, 404].includes(reason.status)
        ) {
          window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
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
      .finally(() => {
        if (version === contextVersion.current) setContextLoading(false);
      });
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, retrieving]);

  async function connectToPatientSearch() {
    if (searchConnecting) return;
    setSearchConnecting(true);
    setSearchError("");
    setSearchResult(null);
    try {
      const session = await createPatientSearchSession();
      window.location.assign(session.authorizationUrl);
    } catch (reason) {
      setSearchError(
        messageFromError(reason, "Could not connect to Epic patient search."),
      );
      setSearchConnecting(false);
    }
  }

  async function submitPatientSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patientSearchSessionId || searchBusy || patientBusy) return;
    const givenName = searchGivenName.trim();
    const familyName = searchFamilyName.trim();
    const birthDate = searchBirthDate;
    if (!givenName || !familyName || !birthDate) {
      setSearchError("Enter given name, family name, and date of birth.");
      return;
    }
    const version = ++searchVersion.current;
    setSearchBusy(true);
    setSearchError("");
    setSearchResult(null);
    try {
      const result = await searchPatients(patientSearchSessionId, {
        givenName,
        familyName,
        birthDate,
      });
      if (version === searchVersion.current) setSearchResult(result);
    } catch (reason) {
      if (version !== searchVersion.current) return;
      if (
        reason instanceof ApiRequestError &&
        [401, 404].includes(reason.status)
      ) {
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setPatientSearchSessionId("");
        setSearchError(
          "Epic patient-search authorization expired. Connect again.",
        );
      } else {
        setSearchError(
          messageFromError(
            reason,
            "Epic patient search could not be completed.",
          ),
        );
      }
    } finally {
      if (version === searchVersion.current) setSearchBusy(false);
    }
  }

  async function selectPatient(candidate: PatientSearchCandidate) {
    if (!candidate.patientId || patientBusy) return;
    setPatientBusy(true);
    setError("");
    setSearchError("");
    try {
      if (patientSearchSessionId) {
        await clearPatientSearchSession(patientSearchSessionId);
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setPatientSearchSessionId("");
      }
      if (sessionId) {
        try {
          await clearSession(sessionId);
        } catch (reason) {
          if (
            !(reason instanceof ApiRequestError) ||
            ![401, 404].includes(reason.status)
          ) {
            throw reason;
          }
        }
        contextVersion.current += 1;
        window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
        setSessionId("");
        setStatus(null);
        setTurns([]);
        setPatientProfile(null);
        setPatientDetailsUnavailable(false);
        setQuestion("");
      }
      const session = await createSession(candidate.patientId);
      window.location.assign(session.authorizationUrl);
    } catch (reason) {
      setSearchError(
        messageFromError(reason, "Could not start the patient session."),
      );
      setPatientBusy(false);
    }
  }

  function openPatientSearch() {
    setSearchGivenName("");
    setSearchFamilyName("");
    setSearchBirthDate("");
    setSearchResult(null);
    setSearchError("");
    setView("search");
  }

  async function returnToChat() {
    try {
      if (patientSearchSessionId) {
        await clearPatientSearchSession(patientSearchSessionId);
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setPatientSearchSessionId("");
      }
      const currentSessionId =
        sessionId || window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
      if (currentSessionId) {
        window.location.assign(
          `/?session_id=${encodeURIComponent(currentSessionId)}`,
        );
      } else {
        setView("search");
      }
    } catch (reason) {
      setSearchError(
        messageFromError(reason, "Could not close the patient-search session."),
      );
    }
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
          <span className="user-avatar" aria-hidden="true">
            S
          </span>
          <span>Demo workspace</span>
        </div>
      </header>
      <main className="page-content chat-page">
        {view === "search" ? (
          <PatientSearch
            sessionId={patientSearchSessionId}
            givenName={searchGivenName}
            familyName={searchFamilyName}
            birthDate={searchBirthDate}
            result={searchResult}
            busy={searchBusy}
            connecting={searchConnecting || patientBusy}
            error={searchError}
            hasCurrentChat={Boolean(sessionId)}
            onGivenNameChange={setSearchGivenName}
            onFamilyNameChange={setSearchFamilyName}
            onBirthDateChange={setSearchBirthDate}
            onConnect={() => void connectToPatientSearch()}
            onSubmit={submitPatientSearch}
            onSelect={(candidate) => void selectPatient(candidate)}
            onReturnToChat={() => void returnToChat()}
          />
        ) : (
          <>
            <section className="patient-banner">
              <div className="patient-avatar" aria-hidden="true">
                P
              </div>
              <div className="patient-identity">
                <p className="section-kicker">Patient Scope</p>
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
                <span
                  className={connected ? "status-dot connected" : "status-dot"}
                />
                <span className={connected ? "status connected" : "status"}>
                  {connectionLabel}
                </span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="end-session"
                onClick={openPatientSearch}
                disabled={patientBusy || busy || contextLoading}
              >
                {connected ? "Search for another patient" : "Find a patient"}
              </Button>
            </section>

            {error && (
              <p role="alert" className="error api-error">
                {error}
              </p>
            )}
            <div className="workspace-layout">
              <aside className="panel chart-sidebar">
                <p className="section-kicker">Workspace</p>
                <h2>Patient context</h2>
                {connected ? (
                  <>
                    <div className="context-row">
                      <span>Patient ID</span>
                      <strong>{status.patientId}</strong>
                    </div>
                    <div className="context-row">
                      <span>Given name</span>
                      <strong>
                        {patientProfile?.givenName ?? "Not available"}
                      </strong>
                    </div>
                    <div className="context-row">
                      <span>Family name</span>
                      <strong>
                        {patientProfile?.familyName ?? "Not available"}
                      </strong>
                    </div>
                    <div className="context-row">
                      <span>Date of birth</span>
                      <strong>
                        {patientProfile?.birthDate ?? "Not available"}
                      </strong>
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
                      <strong>Clinical and Claims reads requested</strong>
                    </div>
                    <div className="context-row">
                      <span>Session</span>
                      <strong>Connection retained; chat not saved</strong>
                    </div>
                  </>
                ) : contextLoading ? (
                  <p className="muted" role="status">
                    Restoring patient context...
                  </p>
                ) : (
                  <p className="muted">
                    Set a Patient FHIR ID to authorize Clinical and Claims
                    access together.
                  </p>
                )}
                <div className="sidebar-note">
                  Chart answers use records available to this authorized
                  session. Review the sources attached to each response.
                </div>
              </aside>

              <section className="panel chat-panel">
                <div className="chat-panel-heading">
                  <div>
                    <p className="section-kicker">Folium Agents</p>
                    <h2>Ask about Clinical or Financials</h2>
                  </div>
                  <span className="read-only-badge">Read only</span>
                </div>
                <section
                  className="conversation"
                  aria-live="polite"
                  aria-label="Conversation"
                >
                  {turns.length === 0 && (
                    <div className="empty-chat">
                      <span className="empty-chat-icon" aria-hidden="true">
                        ?
                      </span>
                      <h3>
                        {connected
                          ? "What would you like to know?"
                          : "Your chat is ready"}
                      </h3>
                      <p className="muted">
                        {connected
                          ? "Ask about the selected patient's clinical chart or claims. Answers use authorized records and disclose missing evidence."
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
                              <summary>
                                Sources ({turn.result.sources.length})
                              </summary>
                              <ul>
                                {turn.result.sources.map((source) => (
                                  <li
                                    key={`${source.sourceType}/${source.sourceId}`}
                                  >
                                    <strong>
                                      {source.sourceType}/{source.sourceId}
                                    </strong>
                                    {" — "}
                                    {source.title}
                                    {source.status && ` · ${source.status}`}
                                    {source.date && ` · ${source.date}`}
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                          {turn.result.limitations?.map((limitation, index) => (
                            <p className="muted" key={`${index}-${limitation}`}>
                              Coverage: {limitation}
                            </p>
                          ))}
                          {turn.result.warnings.map((warning, index) => (
                            <p className="warning" key={`${index}-${warning}`}>
                              Retrieval warning: {warning.replace(/\.$/, "")}.
                              This response may be incomplete.
                            </p>
                          ))}
                        </div>
                      )}
                      {turn.error && (
                        <p role="alert" className="error">
                          {turn.error}
                        </p>
                      )}
                    </article>
                  ))}
                  {retrieving && (
                    <p className="muted" role="status">
                      Retrieving authorized patient data...
                    </p>
                  )}
                  <div ref={endRef} />
                </section>
                <form className="composer" onSubmit={submit}>
                  <label className="sr-only" htmlFor="question">
                    Ask a Clinical or Financials question
                  </label>
                  <textarea
                    id="question"
                    rows={2}
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="Ask about this patient's chart or claims"
                    disabled={!connected || busy}
                  />
                  <Button
                    type="submit"
                    disabled={!connected || busy || !question.trim()}
                  >
                    {busy ? "Sending..." : "Send"}
                  </Button>
                </form>
              </section>
            </div>
            <p className="clinical-disclaimer">
              Synthetic data only. Responses are not a substitute for clinical
              judgment and do not diagnose, recommend treatment, place orders,
              or change the medical record. Financial responses require human
              review; no payments or other financial actions are executed.
            </p>
          </>
        )}
      </main>
      <footer className="ehr-footer">
        Folium Agents demo · Synthetic data only · Not for clinical use
      </footer>
    </div>
  );
}
