(actor knowledge-reviewer
  (:runtime native
   :service-uri "star://starintel:localhost:knowledge-reviewer"
   :accepts (org.starintel/propose-knowledge@1 org.starintel/review-context@1)
   :produces (org.starintel/cast-knowledge-vote@1 org.starintel/audit-finding@1)
   :handler knowledge-reviewer-handler
   :restart permanent
   :mailbox (bounded 1024)
   :metadata ((domain "star-kb") (role "reviewer"))))