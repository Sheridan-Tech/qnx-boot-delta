# Review a QNX startup change before building an image

This tutorial demonstrates a host-side review workflow for QNX 8. You need Python 3.10+ and this checkout. No SDK or target is used in the tutorial. The examples are original analysis fixtures, not bootable images.

## 1. State the intended configuration

The baseline starts a serial driver, declares a wait for `/dev/ser1`, reopens that device as the console, starts an illustrative telemetry consumer, then declares a wait for its resource. The example's project contract requires the serial wait before `telemetry-agent` and caps recognized wait declarations at 12 seconds.

Read `examples/baseline.build` and `examples/review-policy.json`. The named consumer is illustrative; its executable is not included.

## 2. Review the change

```bash
python -m bootdelta examples/baseline.build examples/changed.build --policy examples/review-policy.json --html reports/changed.html --json reports/changed.json
```

The command's exit 1 is expected. Open the HTML file. Start with high-priority findings, then inspect the startup sequence. Follow a source link to the original declaration. Expand effective settings to see why an unchanged-looking launch can be affected by an inherited environment change.

The changed file removes the serial wait, moves the consumer before the console reopen, changes its arguments and execution settings, and extends a telemetry wait. The model sums 17 seconds of recognized timeout declarations, compared with 10 in the baseline. This is a review of configured limits, not elapsed boot timing.

## 3. Separate policy from inference

The missing-barrier finding has two parts: the source comparison records a removed declaration, while the project contract says that this particular declaration is required before a particular consumer. That requirement came from the policy file, not from a guessed device dependency.

The policy cannot ensure that `/dev/ser1` becomes ready. The wait can time out, and resource existence itself is not full service health. QNX runtime testing still serves a different purpose from configuration review.

## 4. Check the correction

```bash
python -m bootdelta examples/baseline.build examples/corrected.build --policy examples/review-policy.json --html reports/corrected.html
```

Expect exit 0 and no modeled differences. This demonstrates that the review gate responds to the corrected declarations. It does not validate target binaries, image assembly, or boot behavior.

## 5. Exercise incomplete coverage

```bash
python -m bootdelta examples/baseline.build examples/incomplete.build --html reports/incomplete.html
```

Expect exit 2. This input explicitly invokes an external `waitfor`; the tool records the declaration but excludes it from the built-in wait model. Read the exclusion reason in HTML or JSON. A partial sum must not be mistaken for an exhaustive one.

## 6. Use the review in an existing QNX project

Compare the appropriate old and new buildfiles with their checkout roots. Keep contracts narrow and tied to your actual integration requirements. Review gaps and source matches. Then use your licensed QNX toolchain and target test process to establish image acceptance and runtime behavior. Boot Delta does not replace those steps.

Reference: [QNX 8 mkifs](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html), especially Script files and Environment variables.
