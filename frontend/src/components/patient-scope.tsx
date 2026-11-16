import { Button } from "@/components/ui/button";
import type { ConnectionStatus, PatientProfile } from "@/lib/api";

type PatientScopeProps = {
  status: ConnectionStatus | null;
  profile: PatientProfile | null;
  detailsUnavailable: boolean;
  loading: boolean;
  disabled: boolean;
  onFindPatient: () => void;
};

export default function PatientScope({
  status,
  profile,
  detailsUnavailable,
  loading,
  disabled,
  onFindPatient,
}: PatientScopeProps) {
  const connected = status?.connected === true;
  const patientName =
    [profile?.givenName, profile?.familyName].filter(Boolean).join(" ") ||
    (connected ? `Patient ${status.patientId}` : "No patient selected");

  return (
    <aside className="panel chart-sidebar" aria-labelledby="patient-scope-title">
      <p className="section-kicker">Workspace</p>
      <h2 id="patient-scope-title">Patient context</h2>
      {connected ? (
        <>
          <div className="context-row">
            <span>Patient ID</span>
            <strong>{status.patientId}</strong>
          </div>
          <div className="context-row">
            <span>Name</span>
            <strong>{patientName}</strong>
          </div>
          <div className="context-row">
            <span>Date of birth</span>
            <strong>{profile?.birthDate ?? "Not available"}</strong>
          </div>
          <div className="context-row">
            <span>Connection</span>
            <strong>EHR connected</strong>
          </div>
          <div className="context-row">
            <span>Access</span>
            <strong>Clinical and Claims reads requested</strong>
          </div>
          <div className="context-row">
            <span>Session</span>
            <strong>Connection retained; chat not saved</strong>
          </div>
          {detailsUnavailable && (
            <p className="muted" role="status">
              Patient details are not available for this connection.
            </p>
          )}
        </>
      ) : loading ? (
        <p className="muted" role="status">
          Restoring patient context...
        </p>
      ) : (
        <p className="muted">
          Select a patient to start a read-only conversation.
        </p>
      )}
      <Button
        variant="secondary"
        size="sm"
        className="context-action"
        type="button"
        onClick={onFindPatient}
        disabled={disabled}
      >
        {connected ? "Change patient" : "Find a patient"}
      </Button>
      <div className="sidebar-note">
        Chart answers use records available to this authorized session. Review
        the sources attached to each response.
      </div>
    </aside>
  );
}
