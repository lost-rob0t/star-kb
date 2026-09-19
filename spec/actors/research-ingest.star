(actor research-ingest
  (:runtime native
   :service-uri "star://starintel:localhost:research-ingest"
   :accepts (org.starintel/research-text@1)
   :produces (org.starintel/propose-knowledge@1)
   :handler research-ingest-handler
   :restart permanent
   :mailbox (bounded 1024)
   :metadata ((domain "star-kb") (role "research-ingest"))))