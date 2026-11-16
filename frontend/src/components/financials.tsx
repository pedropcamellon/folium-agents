"use client";

import { useRef, useState } from "react";
import EpicFinancialClaims from "@/components/epic-financial-claims";
import {
  listFinancialClaims,
  investigateClaim,
  type FinancialClaim,
  type FinancialRun,
} from "@/lib/api";

const proposals: Record<string, string> = {
  review_preview:
    "Review the validated posting preview with a human. No payment has been posted.",
  obtain_evidence:
    "Obtain missing remittance evidence before considering posting.",
  no_posting:
    "Review existing posting and residual balance. Do not post the payment again.",
  escalate: "Escalate unresolved or conflicting evidence to a human reviewer.",
};

export default function Financials({
  initialClaims,
  initialLoadError = "",
  sessionId,
  patientId,
  connected,
}: {
  initialClaims: FinancialClaim[];
  initialLoadError?: string;
  sessionId: string;
  patientId: string;
  connected: boolean;
}) {
  const [source, setSource] = useState("epic");
  return (
    <div>
      <label>
        Financial data source
        <select value={source} onChange={(event) => setSource(event.target.value)}>
          <option value="epic">Epic sandbox</option>
          <option value="synthetic">Local synthetic demo</option>
        </select>
      </label>
      {source === "epic" ? (
        <EpicFinancialClaims
          sessionId={sessionId}
          patientId={patientId}
          connected={connected}
        />
      ) : (
        <SyntheticFinancials
          initialClaims={initialClaims}
          initialLoadError={initialLoadError}
        />
      )}
    </div>
  );
}

function SyntheticFinancials({
  initialClaims,
  initialLoadError = "",
}: {
  initialClaims: FinancialClaim[];
  initialLoadError?: string;
}) {
  const [claims, setClaims] = useState<FinancialClaim[]>(initialClaims);
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, FinancialRun>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState(initialLoadError);
  const locked = useRef(false);

  async function start() {
    if (locked.current || !claims.some((claim) => claim.claimId === selected))
      return;
    const claimId = selected;
    locked.current = true;
    setPending(claimId);
    setErrors((old) => ({ ...old, [claimId]: "" }));
    setRuns((old) => {
      const next = { ...old };
      delete next[claimId];
      return next;
    });
    try {
      const result = await investigateClaim(claimId);
      if (
        result.claimId !== claimId ||
        result.workspaceId !== "synthetic-financials"
      ) {
        throw new Error(
          "Investigation returned mismatched claim/workspace context.",
        );
      }
      setRuns((old) => ({ ...old, [claimId]: result }));
    } catch (error) {
      setErrors((old) => ({ ...old, [claimId]: String(error) }));
    } finally {
      locked.current = false;
      setPending(null);
    }
  }

  async function reloadClaims() {
    setLoadError("");
    try {
      setClaims(await listFinancialClaims());
    } catch (error) {
      setLoadError(
        error instanceof Error ? error.message : "Could not load claims.",
      );
    }
  }

  const run = runs[selected];
  return (
    <section style={{ maxWidth: 900, margin: "auto", padding: 24 }}>
      <h1>Financials — synthetic claims</h1>
      <p>
        Read-only investigation, independent of Clinical and Epic authorization.
        Human review required. No financial actions are executed.
      </p>
      {loadError && (
        <p role="alert">
          {loadError}{" "}
          <button onClick={reloadClaims}>Retry loading claims</button>
        </p>
      )}
      <label htmlFor="claim">Synthetic claim </label>
      <select
        id="claim"
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
      >
        <option value="">Select a claim</option>
        {claims.map((claim) => (
          <option key={claim.claimId} value={claim.claimId}>
            {claim.claimId} — {claim.status} — {claim.currency}{" "}
            {(claim.outstandingCents / 100).toFixed(2)} outstanding
          </option>
        ))}
      </select>
      <button disabled={!selected || pending !== null} onClick={start}>
        {pending ? "Investigating…" : "Investigate Claim"}
      </button>
      <div aria-live="polite">
        {pending && (
          <p>
            Running investigation for {pending}. Results remain attached to that
            claim.
          </p>
        )}
        {errors[selected] && (
          <p role="alert">{errors[selected]} Retry with Investigate Claim.</p>
        )}
        {run && (
          <section aria-label="Investigation result">
            <h2>
              {run.claimId}: {run.status}
            </h2>
            <p>
              Run {run.runId} | {run.workspaceId} | Synthetic
            </p>
            {run.error && <p role="alert">{run.error}</p>}
            <h3>Proposed next step</h3>
            <p>{proposals[run.action] ?? "No validated proposal."}</p>
            <p>
              Human review required. Investigation is not permission to post.
            </p>
            {run.uncertainties.map((item) => (
              <p key={item}>{item}</p>
            ))}
            <h3>Cited evidence</h3>
            <p>{run.citations.join(", ") || "No final citations accepted."}</p>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(run.evidence, null, 2)}
            </pre>
            <h3>Execution trace</h3>
            <ul>
              {run.trace.map((item, index) => (
                <li key={index}>
                  {item.tool}: {item.outcome} ({item.durationMs} ms) —{" "}
                  {item.sourceIds.join(", ")}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </section>
  );
}
