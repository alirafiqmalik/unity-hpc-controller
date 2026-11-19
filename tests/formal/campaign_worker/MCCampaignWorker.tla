-------------------------- MODULE MCCampaignWorker --------------------------
(* Two campaigns and three tasks.  c2 is newer, so each pass handles it    *)
(* first.  c1 = {a, b} with frozen qos "normal"; c2 = {c} with frozen qos  *)
(* "long".  b declares qos "long"; a and c declare none and need one GPU.  *)
EXTENDS CampaignWorker

MCTasks == {"a", "b", "c"}
MCOrder == <<"c2", "c1">>
MCCampaignOf == [t \in MCTasks |-> IF t = "c" THEN "c2" ELSE "c1"]
MCGpus == [t \in MCTasks |-> IF t = "b" THEN 0 ELSE 1]
MCNoQos == "no-qos"
MCDeclaredQos == [t \in MCTasks |-> IF t = "b" THEN "long" ELSE MCNoQos]
MCDefaultQos == [c \in {"c1", "c2"} |-> IF c = "c1" THEN "normal" ELSE "long"]
MCQosNames == {"normal", "long"}
MCQosJobLimit == [q \in MCQosNames |-> IF q = "long" THEN 1 ELSE 2]
MCWideQosJobLimit == [q \in MCQosNames |-> 2]
MCMaxConcurrent == [c \in {"c1", "c2"} |-> IF c = "c1" THEN 2 ELSE 1]
=============================================================================
