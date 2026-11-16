export type ClaimEvidence = {
  claimId: string;
  status: string;
  created: string;
  sourceId: string;
  amounts: {
    category: string;
    value: string;
    currency: string | null;
  }[];
  postingStatus: "unknown";
};

export type PatientClaimSearch = {
  source: string;
  patientId: string;
  claims: ClaimEvidence[];
  pages: number;
  complete: boolean;
  limitations: string[];
};
