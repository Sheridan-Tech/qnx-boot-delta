"""Reproduce the three published QNX 8 host-side review cases."""
import argparse
import json
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "changed": (1, {"high": 4, "medium": 10}, 10.0, 17.0, True),
    "corrected": (0, {}, 10.0, 10.0, True),
    "incomplete": (2, {"high": 3, "medium": 5, "low": 1}, 10.0, 0.0, False),
}

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def verify_browser(out, executable):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((out / "changed.html").as_uri())
        require(page.locator(".finding:visible").count() == 14, "initial findings")
        page.locator('button[data-level="high"]').click()
        require(page.locator(".finding:visible").count() == 4, "high filter")
        page.locator("#search").fill("POLICY_BARRIER_MISSING")
        require(page.locator(".finding:visible").count() == 1, "combined search and filter")
        page.locator("#search").fill("no-matching-finding-123")
        require(page.locator("#no-matches").is_visible(), "empty filter")
        page.locator("#search").fill("")
        page.locator('button[data-level="all"]').click()
        page.locator(".finding:visible details summary").first.click()
        require(page.locator(".finding details[open]").count() >= 1, "effective settings")
        link = page.locator(".finding:visible .source-link").first
        target = link.get_attribute("href")
        link.click()
        require(page.locator('[data-panel="sources"]').is_visible(), "source navigation")
        require(page.locator(target).is_visible(), "source target")
        page.locator('button[data-view="sequence"]').click()
        require(page.locator(".sequence-row:visible").count() > 0, "sequence view")
        page.goto((out / "corrected.html").as_uri())
        require(page.locator(".empty-state").is_visible(), "corrected empty state")
        page.goto((out / "incomplete.html").as_uri())
        require(page.locator(".coverage-alert").is_visible(), "incomplete coverage")
        require(not errors, f"browser errors: {errors}")
        result = {"browser": browser.version, "checks": 10, "page_errors": errors}
        browser.close()
        return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="optional Playwright browser smoke test")
    parser.add_argument("--browser-executable", help="path to installed Chromium/Chrome")
    args = parser.parse_args()
    evidence = {"host": platform.system(), "python": platform.python_version(), "cases": {}}
    with tempfile.TemporaryDirectory(prefix="bootdelta-review-") as directory:
        out = Path(directory)
        for name, (code, counts, before, after, complete) in EXPECTED.items():
            command = [sys.executable, "-m", "bootdelta", "examples/baseline.build",
                       f"examples/{name}.build", "--html", str(out / f"{name}.html"),
                       "--json", str(out / f"{name}.json")]
            if name != "incomplete":
                command += ["--policy", "examples/review-policy.json"]
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors="replace")
            require(run.returncode == code, f"{name}: exit {run.returncode}, expected {code}: {run.stderr}")
            data = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
            actual = dict(Counter(c["level"] for c in data["changes"]))
            require(actual == counts, f"{name}: priority counts {actual}")
            require(data["wait_before"]["total_seconds"] == before, f"{name}: baseline wait")
            require(data["wait_after"]["total_seconds"] == after, f"{name}: changed wait")
            require(data["wait_after"]["complete"] == complete, f"{name}: wait coverage")
            require((out / f"{name}.html").stat().st_size > 0, f"{name}: HTML missing")
            evidence["cases"][name] = {"exit": code, "priorities": actual, "wait_before": before, "wait_after": after, "wait_coverage_complete": complete}
        if args.browser:
            evidence["browser"] = verify_browser(out, args.browser_executable)
    print(json.dumps(evidence, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
