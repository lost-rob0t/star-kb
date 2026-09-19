(actor knowledge-voter
  (:runtime native
   :service-uri "star://starintel:localhost:knowledge-voter"
   :accepts (org.starintel/propose-knowledge@1 org.starintel/review-context@1)
   :produces (org.starintel/cast-knowledge-vote@1)
   :handler knowledge-voter-handler
   :restart permanent
   :mailbox (bounded 2048)
   :metadata ((domain "star-kb") (role "voter"))))