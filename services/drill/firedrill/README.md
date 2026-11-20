# Firedrill files for Marco

Run order: `register` descriptor.json, save `lib/` personas, evaluations and scenarios, `world save` world.json,
`plan`, `apply`, then `run` with a local plan (not committed: it holds absolute paths).
The agent is `services/drill/bridge.py` (jsonl-process driver). It plans and proposes only.
