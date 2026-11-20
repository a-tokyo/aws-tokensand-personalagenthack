# a-tokyo~marco-trip-desk

Read-only Guild agent. It answers travel questions from Marco's Cognee memory and the Senso travel policy. It never books.

- Agent: https://app.guild.ai/users/a-tokyo/agents/marco-trip-desk
- Tools: `marco_cognee_recall` (integration `a-tokyo~marco-cognee`) and `marco_senso_policy_search` (integration `a-tokyo~marco-senso`).
- The integration specs are in `integrations/`. The API keys are Guild credentials, never in code.
- Test: `guild agent test`. Publish: `guild agent save --message <msg> --wait --publish`.
