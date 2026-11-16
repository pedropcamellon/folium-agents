"use client";

import { useRef, useState } from "react";
import { searchEpicClaims } from "@/lib/api";
import type { EpicClaimSearch } from "@/lib/financial-models";

export default function EpicFinancialClaims({
  sessionId,
  patientId,
  connected,
}: {
  sessionId: string;
  patientId: string;
  connected: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<EpicClaimSearch | null>(null);
  const locked = useRef(false);

  async function loadClaims() {
    if (locked.current || !connected || !sessionId) return;
    locked.current = true;
    setPending(true);
    setError("");
    setResult(null);
    try {
      const search = await searchEpicClaims(sessionId);
      if (search.patientId !== patientId) {
        throw new Error("Epic returned claims for a different patient context.");
      }
      setResult(search);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Epic claim search failed.",
      );
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <section aria-label="Epic patient claims">
      <h1>Claims</h1>
      <p>
        Read-only claims for the selected patient across all available dates.
        This uses the same patient authorization as Clinical.
      </p>
      {!connected && (
        <p role="status">
          Select a patient and authorize Clinical and Claims access to continue.
        </p>
      )}
      <button disabled={!connected || pending} onClick={loadClaims}>
        {pending ? "Loading claims..." : "Load all patient claims"}
      </button>
      {pending && <p role="status">Request in progress.</p>}
      {error && <p role="alert">{error}</p>}
      {result && (
        <section aria-label="Epic claim search results">
          <p>
            Source: Epic sandbox | Patient: {result.patientId} | All available
            dates | Pages: {result.pages} |{" "}
            {result.complete ? "Retrieval complete" : "Incomplete"}
          </p>
          {result.limitations.map((limitation) => (
            <p key={limitation}>{limitation}</p>
          ))}
          {result.claims.length === 0 && (
            <p>No claims returned for this patient.</p>
          )}
          <ul>
            {result.claims.map((claim) => (
              <li key={claim.claimId}>
                {claim.sourceId} | {claim.status} | Created: {claim.created} |
                Internal posting status: {claim.postingStatus}
                <ul>
                  {claim.amounts.map((amount, index) => (
                    <li key={index}>
                      {amount.category}: {amount.value}{" "}
                      {amount.currency ?? "Currency unavailable"}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          <p>
            Investigation and posting preview are unavailable for Epic records
            until remittance and internal posting evidence are verified.
          </p>
        </section>
      )}
    </section>
  );
}
