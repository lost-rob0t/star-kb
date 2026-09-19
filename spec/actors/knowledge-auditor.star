(actor knowledge-auditor
  (:runtime native
   :service-uri "star://starintel:localhost:star-kb/knowledge-auditor"
   :accepts (org.starintel/review-context@1 org.starintel/query-observation@1 org.starintel/audit-report@1)
   :produces (org.starintel/audit-finding@1 org.starintel/cast-knowledge-vote@1)
   :handler knowledge-auditor-handler
   :restart permanent
   :mailbox (bounded 1024)
   :metadata ((domain "star-kb") (role "auditor"))))