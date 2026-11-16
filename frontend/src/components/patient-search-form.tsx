"use client";

import type { FormEvent } from "react";
import { Button } from "@/components/ui/button";

type PatientSearchFormProps = {
  givenName: string;
  familyName: string;
  birthDate: string;
  busy: boolean;
  connecting: boolean;
  hasCurrentChat: boolean;
  onGivenNameChange: (value: string) => void;
  onFamilyNameChange: (value: string) => void;
  onBirthDateChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onReturnToChat: () => void;
};

export default function PatientSearchForm({
  givenName,
  familyName,
  birthDate,
  busy,
  connecting,
  hasCurrentChat,
  onGivenNameChange,
  onFamilyNameChange,
  onBirthDateChange,
  onSubmit,
  onReturnToChat,
}: PatientSearchFormProps) {
  return (
    <form className="mt-4 grid gap-3" onSubmit={onSubmit}>
      <div className="grid grid-cols-1 gap-3 min-[761px]:grid-cols-3">
        <div className="grid min-w-0 gap-1">
          <label
            className="text-[0.82rem] font-bold"
            htmlFor="patient-search-given-name"
          >
            Given name
          </label>
          <input
            className="min-w-0 text-[0.9rem]"
            id="patient-search-given-name"
            autoComplete="off"
            maxLength={200}
            value={givenName}
            onChange={(event) => onGivenNameChange(event.target.value)}
            disabled={busy || connecting}
            required
          />
        </div>
        <div className="grid min-w-0 gap-1">
          <label
            className="text-[0.82rem] font-bold"
            htmlFor="patient-search-family-name"
          >
            Family name
          </label>
          <input
            className="min-w-0 text-[0.9rem]"
            id="patient-search-family-name"
            autoComplete="off"
            maxLength={200}
            value={familyName}
            onChange={(event) => onFamilyNameChange(event.target.value)}
            disabled={busy || connecting}
            required
          />
        </div>
        <div className="grid min-w-0 gap-1">
          <label
            className="text-[0.82rem] font-bold"
            htmlFor="patient-search-birth-date"
          >
            Date of birth
          </label>
          <input
            className="min-w-0 text-[0.9rem]"
            id="patient-search-birth-date"
            type="date"
            value={birthDate}
            onChange={(event) => onBirthDateChange(event.target.value)}
            disabled={busy || connecting}
            required
          />
        </div>
      </div>
      <p className="field-help">
        Enter given name, family name, and date of birth. Epic may apply
        additional search requirements or access restrictions.
      </p>
      <div className="mt-1 flex flex-wrap gap-[0.65rem]">
        <Button
          type="submit"
          disabled={
            busy ||
            connecting ||
            !givenName.trim() ||
            !familyName.trim() ||
            !birthDate
          }
        >
          {busy ? "Searching..." : "Search"}
        </Button>
        {hasCurrentChat && (
          <Button
            variant="secondary"
            type="button"
            onClick={onReturnToChat}
            disabled={busy || connecting}
          >
            Return to current chat
          </Button>
        )}
      </div>
    </form>
  );
}
