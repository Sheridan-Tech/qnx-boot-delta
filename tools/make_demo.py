"""Create a paginated video from actual CLI outputs, with explicit provenance.

Optional production dependency: Pillow and ffmpeg. Neither is a runtime
dependency of Boot Delta. This is a readable replay, not a target recording.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
FRAMES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "demo-frames"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(name: str, size: int):
    return ImageFont.truetype(str(FONT_DIR / name), size)


def execute_case(name: str, policy: bool):
    args = [sys.executable, "-m", "bootdelta", "examples/baseline.build", f"examples/{name}.build"]
    if policy:
        args += ["--policy", "examples/review-policy.json"]
    args += ["--json", f"reports/{name}.json", "--html", f"reports/{name}.html"]
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    display = "python " + " ".join(args[1:])
    output = result.stdout + result.stderr
    (ROOT / "reports" / f"{name}.txt").write_text(output, encoding="utf-8")
    return {"command": display, "exit_code": result.returncode, "output": output}


def blocks(output: str):
    return [chunk.strip() for chunk in re.split(r"(?=^\[(?:HIGH|MEDIUM|LOW|COVERAGE)\])", output, flags=re.M)
            if chunk.strip()]


def select(output: str, codes: list[str]):
    matches = [chunk for chunk in blocks(output)
               if any(re.match(r"\[[A-Z]+\] " + re.escape(code) + ":", chunk) for code in codes)]
    return "\n\n".join(matches)


def timestamp(seconds: float):
    whole = int(seconds)
    return f"{whole // 3600:02}:{whole // 60 % 60:02}:{whole % 60:02},000"


def wrap_lines(text: str, width: int = 104):
    lines = []
    for line in text.splitlines():
        if not line:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False,
                                   subsequent_indent="    ", break_long_words=True) or [""])
    return lines


def main():
    DEMO.mkdir(exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    cases = {name: execute_case(name, policy) for name, policy in
             (("changed", True), ("corrected", True), ("incomplete", False))}
    assert [cases[name]["exit_code"] for name in ("changed", "corrected", "incomplete")] == [1, 0, 2]
    (DEMO / "recorded-commands.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    changed = cases["changed"]["output"]
    scenes = [
        (8, "QNX Boot Delta", "A focused review of startup configuration changes", 
         "Working host tool | Python standard library | QNX 8 startup semantics\n\n"
         "This demo replays actual executed CLI output in readable pages.\n"
         "Examples are original synthetic startup fragments.\n"
         "No QNX SDK, QEMU, hardware, or target execution is shown.",
         "We compare the declared startup behavior, then apply an explicit project review contract."),
        (12, "01 / Compare the change", "Actual CLI output · exit 1 requests review",
         "$ python -m bootdelta examples/baseline.build examples/changed.build\n"
         "    --policy examples/review-policy.json --html reports/changed.html\n"
         "    --json reports/changed.json\n\n" + changed.split("[", 1)[0].strip(),
         "The changed configuration increases recognized wait ceilings from 10 to 17 seconds. This is not boot time."),
        (15, "02 / Follow the source evidence", "A required readiness declaration disappears",
         select(changed, ["barrier_removed"]),
         "The report identifies the removed serial-resource wait and its original source line. A removed wait is a review prompt, not proof of failure."),
        (15, "03 / See a timeout edit", "Stable resource paths preserve the before/after comparison",
         select(changed, ["wait_configuration_changed"]),
         "The telemetry wait remains the same resource check, while its configured maximum changes from 3 to 15 seconds."),
        (16, "04 / Inspect the launch declaration", "Background behavior and execution settings are explicit",
         select(changed, ["background_changed", "modifiers_changed"]),
         "The consumer changes from background to foreground and drops its critical modifier. The analyzer does not infer process lifetime."),
        (16, "05 / Apply the project's contract", "The requirements came from the supplied policy file",
         select(changed, ["POLICY_WAIT_LIMIT", "POLICY_BARRIER_MISSING"]),
         "The policy requires a serial wait before every consumer launch and a configured wait sum no larger than 12 seconds."),
        (12, "06 / Verify the correction", "Actual CLI output · exit 0",
         "$ python -m bootdelta examples/baseline.build examples/corrected.build\n"
         "    --policy examples/review-policy.json\n\n" + cases["corrected"]["output"],
         "Restoring the intended declarations produces no modeled differences and passes the explicit review contract."),
        (12, "07 / Keep uncertainty visible", "Actual CLI summary · exit 2",
         "$ python -m bootdelta examples/baseline.build examples/incomplete.build\n\n"
         + cases["incomplete"]["output"].split("[", 1)[0].strip()
         + "\n\n[+external] waitfor is recorded, but excluded from built-in wait semantics.\n"
         "The JSON and HTML reports retain the exclusion reason.",
         "An externally resolved waitfor is not silently treated as the internal command. Incomplete coverage is a distinct CI result."),
        (10, "Ready for a source review", "Reproducible analysis, with clear limits",
         "Included in the package:\n\n"
         "  Original source + MIT license\n"
         "  Behavioral and adversarial tests\n"
         "  Terminal, JSON, and interactive offline HTML reports\n"
         "  Example configurations + project contract\n"
         "  Supported-syntax documentation + tutorial\n\n"
         "No target boot, compiler acceptance, timing improvement,\n"
         "competition acceptance, or prize income is claimed.",
         "The result is a working host analysis tool. Target integration and competition entry remain separate steps."),
    ]
    captions, manifest = [], []
    elapsed = 0
    for index, (duration, title, subtitle, body, caption) in enumerate(scenes):
        image = Image.new("RGB", (1600, 900), "#eef2f5")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1600, 88), fill="#102b3c")
        draw.rounded_rectangle((44, 22, 88, 66), radius=10, fill="#26c5b6")
        draw.text((55, 26), "Δ", font=font("DejaVuSans-Bold.ttf", 27), fill="#102b3c")
        draw.text((106, 28), "QNX Boot Delta", font=font("DejaVuSans-Bold.ttf", 26), fill="#f5fafc")
        draw.text((1170, 34), "ACTUAL CLI OUTPUT REPLAY", font=font("DejaVuSans.ttf", 15), fill="#bdd4df")
        draw.text((55, 119), title, font=font("DejaVuSans-Bold.ttf", 37), fill="#173346")
        draw.text((57, 174), subtitle, font=font("DejaVuSans.ttf", 21), fill="#576d7b")
        draw.rounded_rectangle((45, 226, 1555, 755), radius=12, fill="#142936")
        lines = wrap_lines(body)
        if len(lines) > 22:
            raise ValueError(f"Scene {index} has {len(lines)} lines; paginate rather than truncate output.")
        size = 21 if len(lines) <= 19 else 19
        row_height = 25 if len(lines) <= 19 else 23
        y = 247
        for line in lines:
            color = "#e1eef5"
            if line.startswith("[HIGH]"): color = "#ffadad"
            elif line.startswith("[MEDIUM]"): color = "#ffd18a"
            elif line.startswith("$"): color = "#61dfcd"
            elif "Coverage:" in line: color = "#8ce1d0"
            draw.text((69, y), line, font=font("DejaVuSansMono.ttf", size), fill=color)
            y += row_height
        for offset, line in enumerate(textwrap.wrap(caption, width=118)):
            draw.text((57, 784 + 28 * offset), line, font=font("DejaVuSans.ttf", 22), fill="#264d60")
        draw.text((58, 866), "Linux host analysis • Original fixtures • No target execution", font=font("DejaVuSans.ttf", 14), fill="#5b7381")
        draw.text((1450, 866), f"{index+1:02d} / {len(scenes):02d}", font=font("DejaVuSansMono.ttf", 14), fill="#5b7381")
        path = FRAMES / f"scene-{index:02d}.png"
        image.save(path)
        captions.append(f"{index+1}\n{timestamp(elapsed)} --> {timestamp(elapsed+duration)}\n{caption}\n")
        manifest.append(f"file '{path.as_posix()}'\nduration {duration}\n")
        elapsed += duration
    manifest.append(f"file '{(FRAMES / f'scene-{len(scenes)-1:02d}.png').as_posix()}'\n")
    concat = FRAMES / "frames.txt"
    concat.write_text("".join(manifest), encoding="utf-8")
    (DEMO / "bootdelta-demo.srt").write_text("\n".join(captions), encoding="utf-8")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-vf", "fps=24", "-t", str(elapsed), "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(DEMO / "bootdelta-demo.mp4")], check=True)
    (DEMO / "README.md").write_text(
        "# Demonstration provenance\n\n"
        f"Duration: approximately {elapsed} seconds. Silent, with readable on-screen captions.\n\n"
        "The video is a paginated replay of actual Linux CLI outputs captured by `tools/make_demo.py`. "
        "It is not a live screen recording or a QNX-target recording. Selected finding blocks are shown in full; "
        "the complete raw outputs and executed commands are in `recorded-commands.json` and `reports/*.txt`. "
        "Intro/outro and explanatory captions are authored text.\n\n"
        "The CLI commands run again when generating the demo; their expected exits are checked. "
        "The HTML reports were generated but not browser-interaction tested. No third-party image, music, or logo is used. "
        "Typography uses DejaVu fonts installed on the build host.\n\n"
        "Reproduction: install Pillow and ffmpeg locally, then run `python tools/make_demo.py`. "
        "These are optional demo-production dependencies; the analyzer itself needs only Python's standard library.\n",
        encoding="utf-8")
    print(json.dumps({"duration_seconds": elapsed, "video": str(DEMO / "bootdelta-demo.mp4"), "scenes": len(scenes)}))


if __name__ == "__main__":
    main()
