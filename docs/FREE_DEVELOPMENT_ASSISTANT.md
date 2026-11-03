# LaLa free development assistant

This mode uses ChatGPT with the connected GitHub app and GitHub Actions. It requires no OpenAI API key, and does not install an autonomous coding agent.

## Workflow
1. ChatGPT reads the latest main, relevant PR, tests and CI failures.
2. ChatGPT edits code in an isolated branch and opens a draft PR.
3. GitHub Actions performs no-release PR validation.
4. On a failed CI run, a user can ask ChatGPT to inspect the run logs and make another fix.
5. GitHub retains issues, PR commits, checks and artifacts as checkpoints across conversations.

## Limits
- GitHub Actions cannot invoke the ChatGPT subscription to generate patches.
- Without an external coding agent, failed tests do not automatically generate fixes.
- Scheduled inventory workflows become active only when their workflow file is on the repository default branch, subject to GitHub scheduling restrictions.
- Desktop PR regression is not a Windows EXE packaging acceptance test.
- Android PR diagnostics are not an APK build or real-device test.
- GitHub-hosted Actions usage can incur charges depending on repository visibility, account plan and minutes/storage quotas. Set spending controls in GitHub billing.
- Do not merge, tag or release automatically.

## Suggested resume request
'Continue LaLa development: read latest main, open automation PRs and failing CI runs for both desktop and Android; select the highest-priority bounded task, fix on an independent branch, run tests and update the draft PR. Do not merge or release. Report verified evidence and blockers.'

## Activation checklist
- [ ] Review both draft PRs and verify their checks
- [ ] Verify no-release CI jobs run successfully
- [ ] Review GitHub Actions billing limits and repository protections
- [ ] Merge only approved automation infrastructure changes when ready to activate default-branch scheduling
- [ ] Verify scheduled inventory artifact appears
