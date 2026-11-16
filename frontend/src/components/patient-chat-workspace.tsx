"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiRequestError,
  ConnectionStatus,
  getConnectionStatus,
  getPatientProfile,
  PatientProfile,
} from "@/lib/api";
import Chat from "@/components/chat";
import PatientScope from "@/components/patient-scope";

const ACTIVE_SESSION_STORAGE_KEY = "folium-agents-active-session";

function messageFromError(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export default function PatientChatWorkspace() {
  const router = useRouter();
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [detailsUnavailable, setDetailsUnavailable] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);
  const [chatBusy, setChatBusy] = useState(false);
  const [error, setError] = useState("");
  const contextVersion = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id =
      params.get("session_id") ||
      window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!id) {
      window.location.replace("/patients");
      return;
    }

    const version = ++contextVersion.current;
    setSessionId(id);
    setContextLoading(true);
    getConnectionStatus(id)
      .then((connection) => {
        if (version !== contextVersion.current) return;
        setStatus(connection);
        window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, id);
        if (params.has("session_id")) {
          window.history.replaceState(null, "", "/chat");
        }
        if (connection.connected) {
          void getPatientProfile(id)
            .then((patient) => {
              if (version === contextVersion.current) setProfile(patient);
            })
            .catch(() => {
              if (version === contextVersion.current)
                setDetailsUnavailable(true);
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
      })
      .finally(() => {
        if (version === contextVersion.current) setContextLoading(false);
      });

    return () => {
      contextVersion.current += 1;
    };
  }, []);

  function findPatient() {
    router.push("/patients");
  }

  return (
    <div className="workspace-layout">
      <PatientScope
        status={status}
        profile={profile}
        detailsUnavailable={detailsUnavailable}
        loading={contextLoading}
        disabled={chatBusy || contextLoading}
        onFindPatient={findPatient}
      />
      <div className="chat-workspace-main">
        {error && (
          <p role="alert" className="error api-error">
            {error}
          </p>
        )}
        <Chat
          sessionId={sessionId}
          connected={status?.connected === true}
          onBusyChange={setChatBusy}
        />
      </div>
    </div>
  );
}
