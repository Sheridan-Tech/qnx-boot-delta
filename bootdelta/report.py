"""Offline HTML and terminal presentation of observed configuration deltas."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from html import escape
import json
import re

from .model import Command, Comparison, SourceRef


def is_complete(comparison: Comparison) -> bool:
    return not (comparison.before.coverage or comparison.after.coverage) and \
        comparison.wait_before.complete and comparison.wait_after.complete


def render_text(comparison: Comparison) -> str:
    counts = Counter(change.level for change in comparison.changes)
    lines = ["QNX Boot Delta — startup configuration review", "",
             f"Baseline: {comparison.before.input}", f"Current:  {comparison.after.input}",
             f"Coverage: {'supported subset complete' if is_complete(comparison) else 'INCOMPLETE — inspect gaps'}",
             f"Review priorities: {counts['high']} high / {counts['medium']} medium / {counts['low']} low",
             f"Configured built-in wait ceilings: {comparison.wait_before.total_seconds:g} s → "
             f"{comparison.wait_after.total_seconds:g} s (not measured boot time)", ""]
    for change in comparison.changes:
        lines.append(f"[{change.level.upper()}] {change.code}: {change.title}")
        for label, command in (("before", change.before), ("after", change.after)):
            if command:
                lines.append(f"  {label} {command.source.file}:{command.source.line}: {command.raw.strip()}")
        lines.append("  " + change.detail)
    for label, config in (("baseline", comparison.before), ("current", comparison.after)):
        for gap in config.coverage:
            location = f" {gap.source.file}:{gap.source.line}" if gap.source else ""
            lines.append(f"[COVERAGE] {label}{location} {gap.code}: {gap.message}")
    if not comparison.changes:
        lines.append("No modeled startup changes found.")
    lines += ["", "Static review only: no SDK compilation, target execution, or boot-time validation."]
    return "\n".join(lines) + "\n"


def _source_id(side: str, source: SourceRef) -> str:
    digest = sha256(source.file.encode("utf-8")).hexdigest()[:14]
    return f"src-{side}-{digest}-{source.line}"


def _source_link(side: str, source: SourceRef) -> str:
    return f'<a class="source-link" href="#{_source_id(side, source)}">{escape(source.file)}:{source.line}</a>'


def _command(command: Command | None, side: str) -> str:
    if command is None:
        return '<div class="codecell empty">No corresponding declaration</div>'
    effective = {"modifiers": command.modifiers, "environment": command.env,
                 "background": command.background, "arguments": command.argv}
    data = escape(json.dumps(effective, indent=2, ensure_ascii=False))
    return (f'<div class="codecell"><div class="codehead">{_source_link(side, command.source)}'
            f'<span>{"background" if command.background else "foreground"}</span></div>'
            f'<pre>{escape(command.raw.strip())}</pre>'
            f'<details><summary>Effective settings</summary><pre>{data}</pre></details></div>')


def render_html(comparison: Comparison) -> str:
    """Return a self-contained report. Untrusted text is escaped, never evaluated."""
    complete = is_complete(comparison)
    counts = Counter(change.level for change in comparison.changes)
    changes = []
    for i, change in enumerate(comparison.changes, 1):
        level = change.level if change.level in {"high", "medium", "low"} else "low"
        docs = change.documentation if change.documentation.startswith("https://www.qnx.com/") else "https://www.qnx.com/developers/docs/8.0/"
        changes.append(
            f'<article class="finding" data-level="{level}"><div class="finding-heading">'
            f'<span class="badge {level}">{level} priority</span><span class="rule">{escape(change.code)}</span>'
            f'<span class="finding-number">{i:02d}</span></div><h3>{escape(change.title)}</h3>'
            f'<p>{escape(change.detail)}</p><div class="pair"><div><div class="small-label">BASELINE</div>'
            f'{_command(change.before, "before")}</div><div><div class="small-label">CURRENT</div>'
            f'{_command(change.after, "after")}</div></div>'
            f'<a class="doc-link" href="{escape(docs, quote=True)}" target="_blank" rel="noreferrer">QNX reference ↗</a></article>'
        )
    gaps = []
    for label, config in (("Baseline", comparison.before), ("Current", comparison.after)):
        for gap in config.coverage:
            location = f"{gap.source.file}:{gap.source.line}" if gap.source else "input"
            gaps.append(f'<li><strong>{label} · {escape(gap.code)}</strong> '
                        f'<span class="muted">{escape(location)}</span><br>{escape(gap.message)}</li>')
    for label, budget in (("Baseline", comparison.wait_before), ("Current", comparison.wait_after)):
        for item in budget.items:
            if not item.get("included"):
                source = item.get("source", {})
                location = f"{source.get('file', 'input')}:{source.get('line', '?')}"
                gaps.append(f'<li><strong>{label} · {escape(str(item.get("command", "wait")))}</strong> '
                            f'<span class="muted">{escape(location)}</span><br>'
                            f'{escape(str(item.get("reason", "Wait semantics are outside the supported model.")))}</li>')
    if not comparison.wait_before.complete or not comparison.wait_after.complete:
        gaps.append('<li><strong>Wait totals are partial.</strong> Only the recognized built-in timeout declarations are summed.</li>')
    coverage_html = ('<div class="coverage-alert"><strong>Coverage is incomplete.</strong> '
                     'Do not treat the visible changes as an exhaustive review.<ul>' + ''.join(gaps) + '</ul></div>') if gaps else ''
    sequences = []
    for side, label, config in (("before", "Baseline", comparison.before), ("after", "Current", comparison.after)):
        rows = []
        for command in config.commands:
            builtin = command.name in {"waitfor", "reopen"} and not command.external
            rows.append(f'<li class="sequence-row {"wait" if builtin else ""}"><span class="seq-number">{command.index + 1:02d}</span>'
                        f'<div><code>{escape(command.raw.strip())}</code><div class="seq-meta">'
                        f'{_source_link(side, command.source)} · {"internal wait" if builtin else "launch / internal command"}'
                        f' · {"background" if command.background else "foreground"}</div></div></li>')
        sequences.append(f'<div class="sequence-panel"><h3>{label} <span>{len(config.commands)} commands</span></h3>'
                         f'<ol class="sequence">{"".join(rows)}</ol></div>')
    sources = []
    for side, label, config in (("before", "Baseline", comparison.before), ("after", "Current", comparison.after)):
        for filename, content in config.sources.items():
            rows = []
            for number, line in enumerate(content.splitlines(), 1):
                identifier = _source_id(side, SourceRef(filename, number))
                rows.append(f'<div class="source-line" id="{identifier}"><span>{number}</span><code>{escape(line) or " "}</code></div>')
            sources.append(f'<section class="source-file"><h3>{label} · {escape(filename)}</h3>'
                           f'<div class="source-code">{"".join(rows)}</div></section>')
    before, after = comparison.wait_before.total_seconds, comparison.wait_after.total_seconds
    scale = max(before, after, 1)
    delta = after - before
    heading = "Changes need review" if comparison.changes else "No modeled startup changes"
    if not complete:
        heading = "Review has coverage gaps"
    notes = ''.join(f'<li>{escape(note)}</li>' for note in comparison.notes)
    values = {
        "HEADING": heading,
        "STATUS": "Supported subset complete" if complete else "Incomplete coverage",
        "STATUS_CLASS": "complete" if complete else "incomplete",
        "BASELINE": escape(comparison.before.input), "CURRENT": escape(comparison.after.input),
        "HIGH": str(counts['high']), "MEDIUM": str(counts['medium']), "LOW": str(counts['low']),
        "TOTAL": str(len(comparison.changes)), "BEFORE_WAIT": f"{before:g}", "AFTER_WAIT": f"{after:g}",
        "DELTA": f"{delta:+g}", "BEFORE_WIDTH": f"{100 * before / scale:.2f}", "AFTER_WIDTH": f"{100 * after / scale:.2f}",
        "COVERAGE": coverage_html, "FINDINGS": ''.join(changes) or '<div class="empty-state">No modeled differences. This does not establish that the target boots successfully.</div>',
        "SEQUENCES": ''.join(sequences), "SOURCES": ''.join(sources), "NOTES": notes,
    }
    # Substitute exactly once into the original template. Source text may
    # legitimately contain strings resembling template markers.
    return re.sub(r"@@([A-Z_]+)@@", lambda match: values[match.group(1)], TEMPLATE)


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>QNX Boot Delta · Startup change review</title>
<style>
:root{--bg:#f5f6f8;--panel:#fff;--ink:#172e3e;--muted:#5d6f7c;--line:#dce3e9;--accent:#086f70;--high:#a52d31;--medium:#8c5700;--low:#226d89}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}a{color:var(--accent)}button,input{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #1b9dba;outline-offset:3px}
header{background:#102b3c;color:#f4f9fc;padding:23px max(5vw,24px)}.brand{display:flex;gap:11px;align-items:center;font-size:18px;font-weight:750;letter-spacing:-.3px}.mark{height:30px;width:30px;display:grid;place-items:center;background:#26c5b6;color:#0b2b39;border-radius:7px;font-weight:900}.header-row{display:flex;align-items:center;justify-content:space-between}.header-note{font-size:12px;color:#bed2dc}.container{max-width:1240px;margin:auto;padding:36px 28px 60px}.hero{display:flex;gap:30px;justify-content:space-between;align-items:start}.eyebrow{letter-spacing:1.7px;color:var(--accent);font-size:11px;font-weight:800}h1{font-size:38px;line-height:1.15;letter-spacing:-1.5px;margin:10px 0 16px}h2{font-size:23px;letter-spacing:-.5px;margin:0 0 5px}h3{margin:9px 0;font-size:19px;letter-spacing:-.3px}.sub{max-width:700px;font-size:16px;color:var(--muted);margin:0}.status{white-space:nowrap;border-radius:99px;padding:8px 13px;font-size:12px;font-weight:700}.complete{color:#00665f;background:#dff4ed}.incomplete{color:#894700;background:#fff0cd}.paths{margin:18px 0 26px;display:flex;flex-wrap:wrap;gap:10px;color:var(--muted);font-size:13px}.paths code{background:#e9edf1;padding:3px 8px;border-radius:5px;word-break:break-all}.overview{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:25px 0}.card{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:22px}.metric-row{display:flex;gap:30px;margin-top:13px}.metric strong{font-size:37px;line-height:1.2;display:block}.metric span{font-size:12px;color:var(--muted)}.metric.high strong{color:var(--high)}.metric.medium strong{color:var(--medium)}.metric.low strong{color:var(--low)}.card-title{font-size:13px;font-weight:750}.caption{font-size:12px;color:var(--muted);margin-top:13px}.budget-line{display:grid;grid-template-columns:70px 1fr 55px;gap:10px;align-items:center;font-size:12px;margin:12px 0}.budget-track{height:9px;border-radius:6px;background:#edf0f4;overflow:hidden}.budget-bar{height:9px;background:#8298a6;border-radius:6px}.budget-bar.current{background:var(--accent)}.delta{font-size:12px;font-weight:750;color:var(--accent);float:right}.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:30px 0 24px;overflow:auto}.tabs button{border:0;background:none;color:var(--muted);padding:13px 20px;font-weight:650;white-space:nowrap}.tabs button.active{color:var(--accent);border-bottom:3px solid var(--accent)}[hidden]{display:none!important}.section-intro{display:flex;justify-content:space-between;gap:18px;margin-bottom:18px}.section-intro p{margin:0;font-size:13px;color:var(--muted)}.filters{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.filters button{border:1px solid #c8d3dc;background:white;color:var(--ink);border-radius:6px;padding:7px 12px;font-size:12px}.filters button.active{background:var(--ink);border-color:var(--ink);color:white}.filters input{border:1px solid #c8d3dc;border-radius:6px;padding:7px 11px;min-width:215px;margin-left:auto;background:#fff;font-size:12px}.finding{background:white;border:1px solid var(--line);border-radius:10px;margin:13px 0;padding:22px}.finding-heading{display:flex;gap:12px;align-items:center}.badge{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;padding:4px 7px;border-radius:4px}.badge.high{color:var(--high);background:#fce9e9}.badge.medium{color:var(--medium);background:#fff0d8}.badge.low{color:var(--low);background:#e4f2f8}.rule{font-size:10px;font-family:ui-monospace,monospace;color:var(--muted)}.finding-number{margin-left:auto;color:#8a9ca9;font-size:12px}.finding p{font-size:13px;color:#4d626f;margin:9px 0 18px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:13px}.small-label{font-size:9px;letter-spacing:1.2px;color:var(--muted);font-weight:750;margin:0 0 5px}.codecell{background:#f4f7fa;border:1px solid #e0e7ed;border-radius:6px;padding:11px;min-height:84px;overflow:hidden}.codehead{display:flex;justify-content:space-between;gap:10px;font-size:10px;color:var(--muted)}pre{white-space:pre-wrap;word-break:break-word;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;margin:8px 0}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.codecell.empty{display:flex;align-items:center;color:#70818d;font-size:12px}.codecell details{font-size:11px;color:var(--muted)}.codecell summary{cursor:pointer}.doc-link{display:inline-block;font-size:11px;margin-top:13px;text-decoration:none}.coverage-alert{background:#fff6e5;border:1px solid #eed299;border-radius:10px;padding:18px 22px;font-size:13px;margin:22px 0}.coverage-alert ul{margin-bottom:0;padding-left:20px}.coverage-alert li{margin:10px 0}.muted{color:var(--muted)}.sequence-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.sequence-panel{background:white;border:1px solid var(--line);border-radius:10px;overflow:hidden}.sequence-panel h3{padding:16px 20px;font-size:16px;border-bottom:1px solid var(--line);margin:0}.sequence-panel h3 span{font-size:11px;font-weight:400;color:var(--muted);float:right}.sequence{list-style:none;padding:0;margin:0}.sequence-row{padding:14px 15px;display:flex;gap:14px;border-bottom:1px solid #e8edf1}.sequence-row:last-child{border:0}.sequence-row.wait{background:#ecf7f4}.seq-number{color:#7c919e;font:11px ui-monospace,monospace;min-width:20px;padding-top:4px}.sequence-row code{font-size:12px;word-break:break-all;white-space:pre-wrap}.seq-meta{font-size:10px;color:var(--muted);margin-top:4px}.source-file{background:white;border:1px solid var(--line);border-radius:10px;margin:16px 0;overflow:hidden}.source-file h3{font-size:14px;padding:16px 20px;margin:0;border-bottom:1px solid var(--line)}.source-code{padding:13px 0;overflow:auto}.source-line{display:flex;min-width:max-content;font:12px/1.9 ui-monospace,monospace;padding-right:20px}.source-line>span{width:53px;text-align:right;padding-right:18px;color:#80929f;user-select:none;flex-shrink:0}.source-line code{white-space:pre}.source-line:target{background:#ffedb8}.notes{background:white;border:1px solid var(--line);border-radius:10px;padding:23px;font-size:14px}.notes li{margin:9px 0}.empty-state{background:#edf8f4;padding:30px;border:1px solid #beddd2;border-radius:10px;color:#245e52}.footer{font-size:11px;color:#6b7e8c;border-top:1px solid var(--line);padding-top:17px;margin-top:30px;display:flex;justify-content:space-between;gap:20px}
@media(max-width:760px){.hero{display:block}.status{display:inline-block;margin-top:18px}h1{font-size:30px}.overview,.pair,.sequence-grid{grid-template-columns:1fr}.container{padding:26px 17px}.filters input{width:100%;margin-left:0}.header-note{display:none}.metric-row{gap:35px}.tabs button{padding:11px 14px}}
@media print{body{background:white}.tabs,.filters,.header-note{display:none}[data-panel]{display:block!important}.finding{break-inside:avoid}.container{max-width:none;padding:20px}.source-file{break-before:page}.source-line{font-size:9px}.pair{grid-template-columns:1fr 1fr}}
</style></head><body>
<header><div class="header-row"><div class="brand"><span class="mark">Δ</span> QNX Boot Delta</div><div class="header-note">OFFLINE STARTUP CONFIGURATION REVIEW · v0.1.0</div></div></header>
<main class="container"><section class="hero"><div><div class="eyebrow">A CHANGE REVIEW FOR QNX 8</div><h1>@@HEADING@@</h1><p class="sub">See how a buildfile change reshapes the declared startup sequence, with source evidence for every review finding.</p></div><span class="status @@STATUS_CLASS@@">@@STATUS@@</span></section>
<div class="paths"><span>Baseline <code>@@BASELINE@@</code></span><span>→</span><span>Current <code>@@CURRENT@@</code></span></div>
@@COVERAGE@@
<section class="overview"><div class="card"><div class="card-title">@@TOTAL@@ changes and contract findings</div><div class="metric-row"><div class="metric high"><strong>@@HIGH@@</strong><span>High priority</span></div><div class="metric medium"><strong>@@MEDIUM@@</strong><span>Medium priority</span></div><div class="metric low"><strong>@@LOW@@</strong><span>Low priority</span></div></div><div class="caption">Priorities guide review. They do not establish a runtime defect.</div></div>
<div class="card"><div class="card-title">Configured built-in wait ceilings <span class="delta">@@DELTA@@ s</span></div><div class="budget-line"><span>Baseline</span><div class="budget-track"><div class="budget-bar" style="width:@@BEFORE_WIDTH@@%"></div></div><strong>@@BEFORE_WAIT@@ s</strong></div><div class="budget-line"><span>Current</span><div class="budget-track"><div class="budget-bar current" style="width:@@AFTER_WIDTH@@%"></div></div><strong>@@AFTER_WAIT@@ s</strong></div><div class="caption">Sum of modeled waitfor/reopen maximums. This is not measured boot time or a bound on total boot time.</div></div></section>
<nav class="tabs" aria-label="Report views"><button class="active" data-view="findings" aria-pressed="true">Review findings</button><button data-view="sequence" aria-pressed="false">Startup sequence</button><button data-view="sources" aria-pressed="false">Source evidence</button><button data-view="notes" aria-pressed="false">Scope & interpretation</button></nav>
<section data-panel="findings"><div class="section-intro"><div><h2>What changed</h2><p>Compare the declarations, inspect effective settings, then follow the evidence.</p></div></div><div class="filters" aria-label="Filter findings"><button class="active" data-level="all" aria-pressed="true">All priorities</button><button data-level="high" aria-pressed="false">High</button><button data-level="medium" aria-pressed="false">Medium</button><button data-level="low" aria-pressed="false">Low</button><input id="search" type="search" aria-label="Search findings" placeholder="Search commands, paths, findings…"></div><div id="findings">@@FINDINGS@@</div><p id="no-matches" hidden>No findings match this filter.</p></section>
<section data-panel="sequence" hidden><div class="section-intro"><div><h2>The declared startup order</h2><p>Green rows are modeled internal waitfor/reopen commands. Positions are declarations, not runtime timestamps.</p></div></div><div class="sequence-grid">@@SEQUENCES@@</div></section>
<section data-panel="sources" hidden><h2>Source evidence</h2><p class="muted">Original analyzed text, with line numbers. Reports embed this text and should be reviewed before publication.</p>@@SOURCES@@</section>
<section data-panel="notes" hidden><div class="notes"><h2>What this report establishes</h2><p>Boot Delta compares a documented subset of QNX 8 startup declarations. It does not execute commands, inspect target filesystems, compile an IFS image, or measure a QNX target.</p><ul><li>Internal waits stop waiting when the path is observed or the configured timeout expires. A preceding wait is not proof of successful resource readiness.</li><li>Foreground/background changes and reordered declarations are review prompts. A foreground process may exit or daemonize; its lifetime is not inferred.</li><li>The wait total adds known built-in timeout declarations. Other commands, target scheduling, and excluded behavior are outside that sum.</li><li>Input gaps and ambiguous matching must be inspected. Zero findings is not a successful-boot or safety certification.</li><li>Optional contracts express a project's chosen configuration requirements. They do not add runtime enforcement.</li>@@NOTES@@</ul><p><a href="https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html" target="_blank" rel="noreferrer">Official QNX 8 mkifs reference ↗</a></p></div></section>
<footer class="footer"><span>QNX Boot Delta · Independent host tool for QNX 8 configuration</span><span>Python standard library · No remote services</span></footer></main>
<script>
(()=>{let currentLevel='all';const panels=[...document.querySelectorAll('[data-panel]')];const tabs=[...document.querySelectorAll('[data-view]')];function view(name){for(const p of panels)p.hidden=p.dataset.panel!==name;for(const t of tabs){const active=t.dataset.view===name;t.classList.toggle('active',active);t.setAttribute('aria-pressed',String(active))}}for(const t of tabs)t.addEventListener('click',()=>view(t.dataset.view));const filters=[...document.querySelectorAll('.filters [data-level]')];function filter(){const query=document.getElementById('search').value.toLowerCase();let visible=0;for(const f of document.querySelectorAll('.finding')){f.hidden=!((currentLevel==='all'||f.dataset.level===currentLevel)&&f.textContent.toLowerCase().includes(query));if(!f.hidden)visible++}document.getElementById('no-matches').hidden=visible>0||document.querySelectorAll('.finding').length===0}for(const f of filters)f.addEventListener('click',()=>{currentLevel=f.dataset.level;for(const b of filters){const active=b===f;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))}filter()});document.getElementById('search').addEventListener('input',filter);for(const a of document.querySelectorAll('.source-link'))a.addEventListener('click',()=>view('sources'));if(location.hash.startsWith('#src-'))view('sources');})();
</script></body></html>'''

