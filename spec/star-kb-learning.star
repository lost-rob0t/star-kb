(spec-library "org.starintel/kb-learning@1"
  (:version "0.1.0")

  (enum vote-stance
    (approve reject abstain))

  (enum knowledge-status
    (candidate generated verified rejected superseded))

  (enum verification-decision
    (verified rejected error))

  (message research-text
    (:fields
     ((researchId string :required)
      (text string :required)
      (sourceUri string :optional)
      (contentHash string :optional)
      (collectedAt string :optional)
      (runId string :required))))

  (message propose-knowledge
    (:fields
     ((candidateId string :required)
      (document map :required)
      (proposedBy string :required)
      (specId string :required)
      (specVersion string :required)
      (specDigest string :required)
      (knowledgeStatus knowledge-status :required)
      (runId string :required))))

  (message cast-knowledge-vote
    (:fields
     ((candidateId string :required)
      (voter string :required)
      (stance vote-stance :required)
      (weight integer :required)
      (specId string :required)
      (specVersion string :required)
      (specDigest string :required)
      (reasons (list string) :optional)
      (evidenceIds (list string) :optional)
      (runId string :required))))

  (message verify-knowledge
    (:fields
     ((candidateId string :required)
      (specId string :required)
      (specVersion string :required)
      (specDigest string :required)
      (policy map :required)
      (runId string :required))))

  (message verification-result
    (:fields
     ((candidateId string :required)
      (specId string :required)
      (specVersion string :required)
      (specDigest string :required)
      (verifier string :required)
      (decision verification-decision :required)
      (issues (list string) :optional)
      (approveWeight integer :required)
      (rejectWeight integer :required)
      (abstainWeight integer :required)
      (totalWeight integer :required)
      (runId string :required))))

  (message query-observation
    (:fields
     ((queryId string :required)
      (actor string :required)
      (query string :required)
      (tool string :optional)
      (arguments map :optional)
      (resultIds (list string) :optional)
      (resultHash string :optional)
      (observedAt string :required)
      (runId string :required))))

  (message review-context
    (:fields
     ((reviewId string :required)
      (candidateId string :optional)
      (events (list map) :required)
      (queryObservations (list map) :required)
      (generatedAt string :required)
      (runId string :required))))

  (message audit-finding
    (:fields
     ((findingId string :required)
      (scope string :required)
      (severity string :required)
      (summary string :required)
      (evidenceIds (list string) :optional)
      (proposedFix string :optional)
      (runId string :required))))

  (message improvement-proposal
    (:fields
     ((proposalId string :required)
      (scope string :required)
      (summary string :required)
      (changes (list map) :required)
      (evidenceIds (list string) :optional)
      (runId string :required)))))