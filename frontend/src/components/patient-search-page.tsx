"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  clearPatientSearchSession,
  clearSession,
  createPatientSearchSession,
  createSession,
  PatientSearchCandidate,
  PatientSearchResponse,
  searchPatients,
} from "@/lib/api";
import PatientSearch from "@/components/patient-search";

const ACTIVE_SESSION_STORAGE_KEY = "folium-agents-active-session";
const ACTIVE_PATIENT_SEARCH_STORAGE_KEY =
  "folium-agents-patient-search-session";

function messageFromError(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export default function PatientSearchPage() {
  const [sessionId, setSessionId] = useState("");
  const [hasCurrentChat, setHasCurrentChat] = useState(false);
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [result, setResult] = useState<PatientSearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");
  const searchVersion = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const currentSessionId = window.localStorage.getItem(
      ACTIVE_SESSION_STORAGE_KEY,
    );
    setHasCurrentChat(Boolean(currentSessionId));

    const searchErrorCode = params.get("patient_search_error");
    if (searchErrorCode) {
      setSessionId(
        window.localStorage.getItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY) || "",
      );
      setError(
        searchErrorCode === "authorization_denied"
          ? "Epic authorization was denied. Connect again to search."
          : "Epic patient-search authorization failed. Connect again to search.",
      );
      window.history.replaceState(null, "", "/patients");
      return;
    }

    const searchId =
      params.get("patient_search_session_id") ||
      window.localStorage.getItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
    if (searchId) {
      setSessionId(searchId);
      window.localStorage.setItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY, searchId);
    }
    if (params.has("patient_search_session_id")) {
      window.history.replaceState(null, "", "/patients");
    }
  }, []);

  async function connectToPatientSearch() {
    if (connecting) return;
    setConnecting(true);
    setError("");
    setResult(null);
    try {
      const session = await createPatientSearchSession();
      window.location.assign(session.authorizationUrl);
    } catch (reason) {
      setError(
        messageFromError(reason, "Could not connect to Epic patient search."),
      );
      setConnecting(false);
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || busy || connecting) return;
    const given = givenName.trim();
    const family = familyName.trim();
    if (!given || !family || !birthDate) {
      setError("Enter given name, family name, and date of birth.");
      return;
    }

    const version = ++searchVersion.current;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await searchPatients(sessionId, {
        givenName: given,
        familyName: family,
        birthDate,
      });
      if (version === searchVersion.current) setResult(response);
    } catch (reason) {
      if (version !== searchVersion.current) return;
      if (
        reason instanceof ApiRequestError &&
        [401, 404].includes(reason.status)
      ) {
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setSessionId("");
        setError("Epic patient-search authorization expired. Connect again.");
      } else {
        setError(
          messageFromError(
            reason,
            "Epic patient search could not be completed.",
          ),
        );
      }
    } finally {
      if (version === searchVersion.current) setBusy(false);
    }
  }

  async function selectPatient(candidate: PatientSearchCandidate) {
    if (!candidate.patientId || connecting) return;
    setConnecting(true);
    setError("");
    try {
      if (sessionId) {
        await clearPatientSearchSession(sessionId);
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setSessionId("");
      }

      const previousSessionId = window.localStorage.getItem(
        ACTIVE_SESSION_STORAGE_KEY,
      );
      if (previousSessionId) {
        try {
          await clearSession(previousSessionId);
        } catch (reason) {
          if (
            !(reason instanceof ApiRequestError) ||
            ![401, 404].includes(reason.status)
          ) {
            throw reason;
          }
        }
        window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
        setHasCurrentChat(false);
      }

      const session = await createSession(candidate.patientId);
      window.location.assign(session.authorizationUrl);
    } catch (reason) {
      setError(
        messageFromError(reason, "Could not start the patient session."),
      );
      setConnecting(false);
    }
  }

  async function returnToChat() {
    try {
      if (sessionId) {
        await clearPatientSearchSession(sessionId);
        window.localStorage.removeItem(ACTIVE_PATIENT_SEARCH_STORAGE_KEY);
        setSessionId("");
      }
      window.location.assign("/chat");
    } catch (reason) {
      setError(
        messageFromError(reason, "Could not close the patient-search session."),
      );
    }
  }

  return (
    <PatientSearch
      sessionId={sessionId}
      givenName={givenName}
      familyName={familyName}
      birthDate={birthDate}
      result={result}
      busy={busy}
      connecting={connecting}
      error={error}
      hasCurrentChat={hasCurrentChat}
      onGivenNameChange={setGivenName}
      onFamilyNameChange={setFamilyName}
      onBirthDateChange={setBirthDate}
      onConnect={() => void connectToPatientSearch()}
      onSubmit={submitSearch}
      onSelect={(candidate) => void selectPatient(candidate)}
      onReturnToChat={() => void returnToChat()}
    />
  );
}
