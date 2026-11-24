# Judge quickstart — QNX Boot Delta

**Category:** Developer Tooling & Host Tools. **Target:** QNX 8.0 startup configuration (host-based analysis). **Host toolchain:** Python 3.10+, standard library; validated on Linux and Windows. No target, QEMU, or QNX SDK is needed to reproduce the host-tool demonstration. No QNX image-build or target-execution validation is claimed.

## Reproduce in two commands

From the repository root:

```text
python -m unittest discover -s tests
python tools/verify_examples.py
```

The second command independently generates fresh HTML and JSON, checks the three documented exit codes, exact finding priorities, wait declaration sums, and incomplete coverage. It exits 0 only when the expected results match. To inspect a fresh interactive report:

```text
python -m bootdelta examples/baseline.build examples/changed.build --policy examples/review-policy.json --html reports/changed.html --json reports/changed.json
```

Exit 1 is intentional: the configuration violates review contracts. Open the HTML report in a browser. No network is needed.

## Where the QNX-specific evidence lives

| QNX 8.0 behavior | Source | Reproducible evidence |
| --- | --- | --- |
| Inline `[+script]` startup declarations and persistent vs command-local settings | [parser.py](../bootdelta/parser.py), [baseline.build](../examples/baseline.build) | Effective settings and source evidence in HTML |
| Internal `waitfor` and `reopen` declarations vs external invocations | [compare.py](../bootdelta/compare.py), [incomplete.build](../examples/incomplete.build) | Built-in wait totals and excluded external wait; exit 2 |
| QNX launch modifiers (`pri`, `critical`, `session`, etc.) and foreground/background changes | [changed.build](../examples/changed.build), [compare.py](../bootdelta/compare.py) | Source-linked findings and ordered startup view |
| Explicit device-readiness ordering and timeout policy | [policy.py](../bootdelta/policy.py), [review-policy.json](../examples/review-policy.json) | POLICY_BARRIER_MISSING and POLICY_WAIT_LIMIT |
| Corrected declarations | [corrected.build](../examples/corrected.build) | Zero findings, exit 0 |

The language model is tied to the [QNX 8 mkifs reference](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html), [startup script guide](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/buildfiles/nto_script.html), and [supported syntax contract](SUPPORTED_SYNTAX.md). These are references, not claims that QNX proprietary tools were executed.

## Demonstration map

[YouTube demo](https://youtu.be/SWk63OZbRBE) (1:56; English captions, silent; replay of actual CLI output).

- 0:08–0:20: configured timeout comparison.
- 0:20–0:50: source-linked QNX wait changes.
- 0:50–1:22: launch settings and explicit project requirements.
- 1:22–1:34: corrected configuration passes.
- 1:34–1:46: external command coverage is flagged instead of guessed.

See [demonstration provenance](../demo/README.md) and [tutorial](TUTORIAL.md).

## Validation update — November 24, 2026

Version 0.1.1 fixes redirected console output under legacy Windows encodings; JSON and HTML remain UTF-8. A regression test explicitly forces CP1252. All 78 unit and adversarial tests passed on Windows / Python 3.14.7. Fresh CLI reproduction and ten report interaction checks passed in headless Chrome, with no JavaScript page errors. [Recorded reproduction](../reports/judge-reproduction-windows.json). The GitHub Actions matrix is provided for repeatable cross-platform validation; consult actual run results before treating any matrix job as passed.

Optional browser verification requires Playwright installed on the host and either its Chromium browser or an installed Chrome executable:

```text
python -m pip install playwright
python -m playwright install chromium
python tools/verify_examples.py --browser
```

For an existing Chrome installation, add `--browser-executable PATH`. Playwright is optional validation tooling, not an analyzer dependency.

## Scope and potential impact

The tool targets pre-integration review of QNX BSP/startup changes in embedded products. It does not determine whether a device actually becomes ready, predict elapsed boot time, prove safety, or replace `mkifs`, target integration, or runtime tests. The bundled examples are intentionally synthetic startup fragments, not complete BSPs.
