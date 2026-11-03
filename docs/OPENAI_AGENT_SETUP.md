# OpenAI API agent provisioning (not yet enabled)

## Required user configuration
1. Create an API project and a project-scoped API key in the OpenAI API platform. ChatGPT subscriptions do not include API billing.
2. Set a conservative project budget and alerts. Never paste the key into chats, issues, commits or logs.
3. In each repository's Settings > Secrets and variables > Actions, create secret `OPENAI_API_KEY`. If supported, prefer a separate environment with reviewer protection.
4. Set repository variable `OPENAI_MODEL` to an API model your project can access. Do not assume availability from ChatGPT plan.
5. Keep the key inaccessible to workflows triggered by untrusted pull requests.

## Deployment steps still pending
- Verify current CI and artifact paths, branch protection and repository permissions.
- Install a sandboxed coding agent pinned to a reviewed version; test a harmless task via manual dispatch.
- Restrict agent to agent-ready issues, isolated automation branches and draft PRs.
- Implement token/time budgets, max two retries, structured checkpoints, and automatic stop on permission/security errors.
- Enable scheduled agent execution only after successful manual dry run.
- No merge, tagging, publishing or live production server access.

## Current state
Only a read-only scheduled inventory workflow is staged in a draft PR. API secrets are not configured by this change. No AI model calls or code generation are enabled.
