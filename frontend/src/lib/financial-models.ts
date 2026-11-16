export type EpicClaimEvidence = {
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

export type EpicClaimSearch = {
  source: "epic-sandbox";
  patientId: string;
  claims: EpicClaimEvidence[];
  pages: number;
  complete: boolean;
  grantedScope: string | null;
  limitations: string[];
};
