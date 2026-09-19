(actor knowledge-verifier
  (:runtime native
   :service-uri "star://starintel:localhost:star-kb/knowledge-verifier"
   :accepts (org.starintel/verify-knowledge@1)
   :produces (org.starintel/verification-result@1)
   :handler knowledge-verifier-handler
   :restart permanent
   :mailbox (bounded 512)
   :metadata ((domain "star-kb") (role "formal-verifier") (engine "prolog"))))