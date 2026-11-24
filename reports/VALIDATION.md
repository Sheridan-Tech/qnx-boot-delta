# Executed validation report

Date: November 18, 2026.

Host: Linux x86_64; Python 3.12.14.

## Automated suite

`python -m unittest discover -s tests -v`

Result: PASS. Full actual output is in `test-results.txt`.

## Integration checks

| Input | Exit | Findings | Known wait sum | Supported coverage |
|---|---:|---:|---|---|
| changed | 1 | 14 | 10 → 17 s | complete |
| corrected | 0 | 0 | 10 → 10 s | complete |
| incomplete | 2 | 9 | 10 → 0 s | incomplete |

The changed and corrected cases use `examples/review-policy.json`. The incomplete case excludes an external wait from the built-in model. Exact terminal, JSON, and HTML outputs are retained in this directory.

## Material checks actually performed

- Scope and inheritance cases: persistent/local modifiers and environment, multiple sections, bootstrap environment, external versus internal command interpretation.
- Comparison cases: order inversions, insertion offsets, duplicate cardinality and ambiguous edited duplicates, uniquely identifiable wait-path edits.
- Parser boundary cases: root-relative includes, traversal/symlink escape, cycles, repeated includes, byte limits, quoted text, unsupported constructs, inline continuation boundaries, cd-controlled includes, and filtered payloads.
- Policy cases: missing/misordered consumer barrier, invalid timeouts, absent consumers, incomplete coverage, unknown keys, oversized numeric limits.
- Output cases: valid JSON numeric values, source text escaping, literal template marker preservation, separate outputs and source overwrite protection including hardlinks.
- CLI integration: review exit1, corrected exit0, incomplete exit2, real report generation, missing inputs.

## Limits and unperformed checks

No licensed QNX SDP, mkifs, QEMU, or target execution was used. Synthetic fixtures establish implementation behavior within the supported subset, not differential equivalence to mkifs. No boot-time, real-time, security, or target reliability claim has been tested.

HTML content/escaping and report creation were tested programmatically. A cloud-browser visual check was blocked because its URL policy does not permit local file navigation. No browser interaction/visual validation is claimed. The packaged demonstration replays actual CLI outputs in readable pages; it is not a QNX target screen recording.

No third-party publication, competition entry acceptance, payment, or revenue is established by these tests.

## Publication preparation

Absolute analysis-root paths in the three generated JSON reports were replaced with `<project>/examples`. Configuration observations and recorded test results are unchanged. Internal account and submission-preparation notes are excluded from this public checkout.

## Additional Windows execution check

On November 18, 2026, the published package was unpacked on Windows and its archive and file-manifest hashes were verified before execution. Python 3.14.7 ran the changed, corrected, and incomplete CLI examples with UTF-8 mode. Their exit codes were 1, 0, and 2 respectively, with no stderr output. The changed and corrected cases used the packaged review policy. See [the recorded outputs](windows-execution.json). This was a three-case host check; the full 77-test suite was not rerun on Windows. No QNX target execution occurred.


## November 24, 2026 follow-up — version 0.1.1

Fresh checkout on Windows, Python 3.14.7: the original full suite exposed two CLI failures when stdout was redirected to a legacy Windows encoding. The console writer now escapes only characters that the active encoding cannot represent; structured JSON and HTML remain UTF-8. The new CP1252 regression test passes, and the complete updated suite passes (78 tests). All three example cases pass the independent fresh-report verifier without a forced UTF-8 environment. Optional Playwright checks in headless Chrome 157 passed ten functional checks and recorded no JavaScript page errors. See [machine-readable evidence](judge-reproduction-windows.json) and [judge guide](../docs/JUDGE_GUIDE.md). The earlier Linux evidence is historical and remains unchanged. No licensed SDK, QEMU, or target validation was performed.
