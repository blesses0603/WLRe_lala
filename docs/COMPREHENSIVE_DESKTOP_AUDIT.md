# Desktop integration audit (2026-11-07)

This local branch integrates the previously separate desktop fixes without
changing main, version tags, releases, or live game accounts.

## Corrections and review coverage

- Navigation cache preparation runs in a cancellable background job and never
  resumes movement automatically. Scene/runtime changes discard stale results.
- Full startup retries re-run official source preparation. Unknown ItemData
  revisions remain blocked even when their downloads succeed.
- Official server-line identity and endpoint changes clear stale credentials.
- Daily receipt epochs, item deltas, and assistant fight capacity retain the
  separate safety-audit corrections in commit c3e3f77.
- User-visible chat, last-response and background observation clocks use UTC+8.
  Internal observation timestamps remain UTC. Daily resets remain authoritative
  server updates; no local-midnight rule was invented.
- Unwritable diagnostic directories/files and unavailable consoles no longer
  replace the original startup error with another exception.
- Portable GUI synchronization fixtures were updated; a raw docstring avoids a
  Python invalid-escape warning in the resource classification utility.

## Verification

- Headless full regression: 2267 tests, OK, 215 skipped (display/platform or other
  explicit conditions). This is not a GUI pass.
- Python compileall and strict repository audit passed.
- Source self-test and UnityFS extractor self-test passed.
- Windows and macOS arm64/x64 build plans passed (dry runs, not native builds).
- Full Tk 8.6 regression at 1440x900: 2267 tests, OK, 3 skipped; GUI smoke passed.
- Focused 1280x720 GUI regression: 87 tests, OK, 1 skipped (requires a taller screen).
  Covers prelogin/version UI, navigation synchronization and daily assistant UI.
- Isolated seedless cold startup passed after all new modules were included in Git.

## Limits

No official-server login, movement, purchases, daily task execution or live
end-to-end game behavior was exercised. No Windows/macOS native binary was
compiled or run in this Linux environment. A passing regression suite does not
establish that all gameplay or all map positions are correct.

## Windows follow-up verification (2026-11-07)

- Applied patch SHA-256
  `f0ab0133a0b6fdd880bb77cdfd20943ebc994c757077d7eb48f885dc7cc4eb02`;
  initial staged tree matched `e86b64fa56962c4517d4f9de659999af2f7f3a47`.
- Local Windows / Python 3.14.8 full regression initially exposed an invalid
  Combobox callback after the login window was destroyed. Label refresh now
  tolerates destroyed widgets while credential invalidation still completes.
- Added regression coverage for destroyed widgets, Tcl teardown and live label
  updates, including a real Tk Combobox.
- Portable tests copy ordinary resource fixtures rather than requiring symlink
  privileges. Corrupt-database validation remains separate from the symlink
  case; only Windows privilege error 1314 skips the actual symlink case.
- Native focus coverage verifies application behavior without assuming every
  Tk/Python version raises KeyError for a native popdown.
- Final Windows full regression: 2273 tests, OK, 9 skipped, 379.6 seconds.
  Focused affected suite: 69 tests, OK, 1 skipped.
- Final compileall, strict repository audit and GUI smoke test passed.
  Source/UnityFS self-tests and Windows/macOS build dry runs also passed.
- No native installer was compiled and no live game login/action was performed.
