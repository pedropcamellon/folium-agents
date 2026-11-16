"use client";

import type { FormEvent } from "react";
import {
  type PatientSearchCandidate,
  type PatientSearchResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import PatientSearchForm from "@/components/patient-search-form";
import PatientSearchResults from "@/components/patient-search-results";

type PatientSearchProps = {
  sessionId: string;
  givenName: string;
  familyName: string;
  birthDate: string;
  result: PatientSearchResponse | null;
  busy: boolean;
  connecting: boolean;
  error: string;
  hasCurrentChat: boolean;
  onGivenNameChange: (value: string) => void;
  onFamilyNameChange: (value: string) => void;
  onBirthDateChange: (value: string) => void;
  onConnect: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSelect: (candidate: PatientSearchCandidate) => void;
  onReturnToChat: () => void;
};

export default function PatientSearch({
  sessionId,
  givenName,
  familyName,
  birthDate,
  result,
  busy,
  connecting,
  error,
  hasCurrentChat,
  onGivenNameChange,
  onFamilyNameChange,
  onBirthDateChange,
  onConnect,
  onSubmit,
  onSelect,
  onReturnToChat,
}: PatientSearchProps) {
  return (
    <section
      className="panel mx-auto my-5 w-full max-w-[900px] p-[clamp(1.1rem,3vw,2rem)]"
      aria-labelledby="patient-search-title"
    >
      <p className="section-kicker">Patient Scope</p>
      <h1 id="patient-search-title">Find a patient</h1>
      <p className="muted">
        Search patients available to your authorized Epic account. Results are
        candidates, not a complete patient list.
      </p>

      {sessionId ? (
        <PatientSearchForm
          givenName={givenName}
          familyName={familyName}
          birthDate={birthDate}
          busy={busy}
          connecting={connecting}
          hasCurrentChat={hasCurrentChat}
          onGivenNameChange={onGivenNameChange}
          onFamilyNameChange={onFamilyNameChange}
          onBirthDateChange={onBirthDateChange}
          onSubmit={onSubmit}
          onReturnToChat={onReturnToChat}
        />
      ) : (
        <div className="mt-4 grid gap-3">
          <p className="field-help">
            Connect with your provider account to search authorized patient
            demographics. Selecting a result will open the existing patient
            authorization flow for chat.
          </p>
          <Button type="button" onClick={onConnect} disabled={connecting}>
            {connecting ? "Connecting..." : "Connect to Epic to search"}
          </Button>
          {hasCurrentChat && (
            <Button
              variant="secondary"
              type="button"
              onClick={onReturnToChat}
              disabled={connecting}
            >
              Return to current chat
            </Button>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="muted">
          Searching authorized Epic records...
        </p>
      )}
      {result && result.candidates.length === 0 && (
        <p role="status" className="muted">
          No results found. Check the search details or confirm the patient is
          available to your authorized Epic account.
        </p>
      )}
      {result && result.candidates.length > 0 && (
        <PatientSearchResults
          result={result}
          connecting={connecting}
          onSelect={onSelect}
        />
      )}
    </section>
  );
}
