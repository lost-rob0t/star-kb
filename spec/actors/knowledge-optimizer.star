(actor knowledge-optimizer
  (:runtime native
   :service-uri "star://starintel:localhost:knowledge-optimizer"
   :accepts (org.starintel/review-context@1 org.starintel/audit-finding@1)
   :produces (org.starintel/improvement-proposal@1)
   :handler knowledge-optimizer-handler
   :restart permanent
   :mailbox (bounded 512)
   :metadata ((domain "star-kb") (role "optimizer"))))