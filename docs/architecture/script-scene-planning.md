# Script and Scene Planning

Milestone 5 adds local, deterministic script and scene planning for the AI & Future MVP.

The pipeline is:

1. Research readiness is evaluated from approved sources and verified claims.
2. A script content version is generated with a replaceable text-provider interface.
3. Script approval is requested before scene planning can proceed.
4. A fact-check report compares the script against project claims.
5. An approved script is converted into a strict JSON scene plan.
6. Scene rows are persisted for dashboard review and later media generation milestones.

The default provider is `local_rules`, which has no paid API or recurring cost. Future local model
providers can implement the same text generation interface without changing application services.
