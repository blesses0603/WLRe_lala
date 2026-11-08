# Optional reviewed skill resources

Resource preparation now looks for the exact `Assets/ResourcesBuild/Data/SkillData_C.bytes`
asset in its already checked DataPackage manifest after decoding the ten required tables.
It acquires only that root and its declared complete dependency set. Existing owned dependencies
are reused. Additional bundles share the remaining file/byte download quota and 32 MiB retained
bundle bound; optional acquisition cannot reset either budget. Existing cached files are checked
and reopened under the same rules as required bundles. No cache files are written.

Native extraction feeds the existing `SkillDataParser.Parse`. Its compiled reviewed SHA-256 is
unchanged and is required before any skill rows are exposed or the raw payload is added to the
inventory input. Unknown, missing, over-budget, transport-failed or malformed optional payloads
leave skills unavailable. Cancellation, failed cleanup and final source drift remain attempt
failures. Combined download metrics include optional planned reservations, even when later
optional extraction or parsing fails.

Accepted bytes are persisted in the existing inventory transaction beside the ten required
tables. Immutable-row conflicts and uncertain writes still fail the entire bootstrap; there is
no compensating rewrite or optional retry that conceals a database conflict. Optional acquisition
failure and optional persisted-readback mismatch are different from such storage failures.

The reader opts into one additional SkillData row in the same read transaction. Required matching
stays exactly ten-table matching. Optional readback checks both recorded and actual payload hashes
against the fixed reviewed skill digest. Missing, malformed or nonmatching optional data drops
skills from the published candidate while preserving valid required tables. Provider failures,
cancellation and cleanup failure still fail the read. Existing inspection/default reader behavior
remains unchanged and does not claim optional completeness.

`OfflineRuntimeCandidate.OptionalSkills` is null when unavailable. Its rows are immutable,
point-in-time data, not login or packet permission. `SourceSha256` keeps its existing ten-required-
table contract. The unavailable-source list removes SkillData only when those optional rows are
present. Receive integration remains a separate consumer of this catalog, with no command gate
change. Other optional data, images and full offline startup remain unimplemented.

## Evidence limits

The synthetic optional UnityFS fixture contains a valid-layout skill row but deliberately does
not match the reviewed production digest. Tests must therefore keep it unavailable; no test-only
production pin override was added. Synthetic tests cover acquisition, quotas, optional failures,
cancellation, fixed-pin rejection and independent optional SQLite readback. A successful end-to-end
publication of the actual reviewed SkillData bytes has not been demonstrated. No official network,
real account, real user database or Desktop UI is used or changed.

Focused Release verification passed 492/492 cases without skips: owner/bootstrap/facade,
required and optional bundle preparation, required and optional database reads/matching, and
retained Python database-read parity. The initial test compile stopped on an xUnit assertion-style
analyzer error; the assertion was corrected and the full focused selection then passed.
Independent static review found no remaining blocker after cleanup-failure propagation and
optional download-accounting corrections. Combined host/full-suite verification is separate.
