import type {
  PatientSearchCandidate,
  PatientSearchResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

type PatientSearchResultsProps = {
  result: PatientSearchResponse;
  connecting: boolean;
  onSelect: (candidate: PatientSearchCandidate) => void;
};

function candidateName(candidate: PatientSearchCandidate): string {
  const name = [candidate.givenName, candidate.familyName]
    .filter(Boolean)
    .join(" ");
  return name || "Name unavailable";
}

export default function PatientSearchResults({
  result,
  connecting,
  onSelect,
}: PatientSearchResultsProps) {
  return (
    <div className="mt-5" aria-live="polite">
      <h2 className="!mb-[0.65rem]">Search matches</h2>
      <div className="overflow-x-auto rounded border border-[var(--line)] bg-white">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              <th
                scope="col"
                className="border-b border-[var(--line)] bg-[#f5f8fa] px-[0.8rem] py-[0.65rem] text-[0.78rem]"
              >
                Patient
              </th>
              <th
                scope="col"
                className="border-b border-[var(--line)] bg-[#f5f8fa] px-[0.8rem] py-[0.65rem] text-[0.78rem]"
              >
                Date of birth
              </th>
              <th
                scope="col"
                className="border-b border-[var(--line)] bg-[#f5f8fa] px-[0.8rem] py-[0.65rem] text-[0.78rem]"
              >
                Action
              </th>
            </tr>
          </thead>
          <tbody>
            {result.candidates.map((candidate) => (
              <tr
                key={candidate.patientId}
                className="[&:last-child>td]:border-b-0"
              >
                <td className="border-b border-[var(--line)] px-[0.8rem] py-[0.65rem]">
                  {candidateName(candidate)}
                </td>
                <td className="border-b border-[var(--line)] px-[0.8rem] py-[0.65rem]">
                  {candidate.birthDate ?? "Not available"}
                </td>
                <td className="whitespace-nowrap border-b border-[var(--line)] px-[0.8rem] py-[0.65rem]">
                  <Button
                    size="sm"
                    type="button"
                    onClick={() => onSelect(candidate)}
                    disabled={connecting || result.moreMatchesAvailable}
                  >
                    {connecting
                      ? "Connecting..."
                      : result.moreMatchesAvailable
                        ? "Refine search"
                        : "Select patient"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.moreMatchesAvailable && (
        <p className="field-help" role="status">
          More matches may be available. Add demographic details to refine the
          search before selecting a patient.
        </p>
      )}
    </div>
  );
}
