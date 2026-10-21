#!/usr/bin/env python3
"""Render the README screenshots: one image per scene.

Each scene runs statusline.sh on a sample session inside a throwaway git repo,
turns the ANSI output into HTML and screenshots it with headless Chromium, so
the images always show what the script really prints.

Needs bash, jq, git, Chromium and the JetBrains Mono font. Easiest via Docker:

    docker build -t claude-statusline-render docs
    docker run --rm -v "$PWD":/repo -w /repo claude-statusline-render python3 docs/render.py
"""
import html
import json
import struct
import zlib
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
CHROME = os.environ.get("CHROME", "chromium")

# Sizes in CSS px. JetBrains Mono advances 0.6em, so 14px text is 8.4px a cell.
FONT, CELL, LINE = 14, 8.4, 22
MARGIN, PAD, TITLE = 28, 16, 34
SCALE = 2

HOUR = 3600
SCENES = [
    {
        "file": "everyday",
        "title": "~/my-app",
        "cols": 120,
        "repo": ("my-app", "main", 0, 2),
        "chat": [("user", "fix the login redirect loop"),
                 ("claude", "Fixed: the session cookie was set after the redirect. Updated 2 files.")],
        "data": {
            "session_name": "fix-login-bug", "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "medium"},
            "context_window": {"used_percentage": 34, "context_window_size": 200000,
                               "total_input_tokens": 68000, "total_output_tokens": 2100},
            "cost": {"total_cost_usd": 2.18, "total_duration_ms": 21 * 60000,
                     "total_lines_added": 84, "total_lines_removed": 12},
            "rate_limits": {"five_hour": {"used_percentage": 28, "resets_at": 3 * HOUR + 300},
                            "seven_day": {"used_percentage": 9, "resets_at": 122 * HOUR}},
        },
    },
    {
        "file": "on-pace",
        "title": "~/my-app",
        "cols": 120,
        "repo": ("my-app", "feat/checkout", 1, 3),
        "chat": [("user", "now wire the checkout form to the payments API"),
                 ("claude", "Wiring the form up. Reading the payments client first.")],
        "data": {
            "session_name": "checkout-flow", "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "medium"},
            "context_window": {"used_percentage": 72, "context_window_size": 200000,
                               "total_input_tokens": 144000, "total_output_tokens": 6800},
            "cost": {"total_cost_usd": 6.40, "total_duration_ms": 98 * 60000,
                     "total_lines_added": 312, "total_lines_removed": 41},
            "rate_limits": {"five_hour": {"used_percentage": 54, "resets_at": 2 * HOUR + 1200},
                            "seven_day": {"used_percentage": 23, "resets_at": 101 * HOUR}},
        },
    },
    {
        "file": "red",
        "title": "~/platform",
        "cols": 120,
        "repo": ("platform", "refactor/auth", 4, 6),
        "chat": [("user", "keep going with the auth refactor"),
                 ("claude", "Moving the token checks into middleware. 6 files left.")],
        "data": {
            "session_name": "auth-refactor", "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "high"}, "fast_mode": True,
            "context_window": {"used_percentage": 93, "context_window_size": 200000,
                               "total_input_tokens": 186000, "total_output_tokens": 9100},
            "cost": {"total_cost_usd": 14.85, "total_duration_ms": 133 * 60000,
                     "total_lines_added": 640, "total_lines_removed": 212},
            "rate_limits": {"five_hour": {"used_percentage": 71, "resets_at": 3 * HOUR},
                            "seven_day": {"used_percentage": 58, "resets_at": 110 * HOUR}},
        },
    },
    {
        "file": "fresh",
        "title": "~/my-app",
        "cols": 120,
        "repo": ("my-app", "main", 0, 0),
        "chat": [("user", "morning! what's left on the release checklist?"),
                 ("claude", "Three items: changelog, version bump and the smoke test.")],
        "data": {
            "session_name": "release-prep", "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "low"},
            "context_window": {"used_percentage": 6, "context_window_size": 200000,
                               "total_input_tokens": 12000, "total_output_tokens": 400},
            "cost": {"total_cost_usd": 0.21, "total_duration_ms": 2 * 60000,
                     "total_lines_added": 0, "total_lines_removed": 0},
            "rate_limits": {"five_hour": {"used_percentage": 2, "resets_at": 4 * HOUR + 3060},
                            "seven_day": {"used_percentage": 31, "resets_at": 26 * HOUR}},
        },
    },
    {
        "file": "api-key",
        "title": "~/data-pipeline",
        "cols": 120,
        "repo": ("data-pipeline", "main", 0, 1),
        "chat": [("user", "summarise the failing ingestion runs from last night"),
                 ("claude", "4 runs failed, all on the same malformed CSV header.")],
        "data": {
            "model": {"display_name": "Sonnet 5.5"},
            "context_window": {"used_percentage": 22, "context_window_size": 1000000,
                               "total_input_tokens": 221000, "total_output_tokens": 5400},
            "exceeds_200k_tokens": True,
            "cost": {"total_cost_usd": 3.41, "total_duration_ms": 14 * 60000,
                     "total_lines_added": 3, "total_lines_removed": 0},
        },
    },
    {
        "file": "worktree",
        "title": "~/my-app/.worktrees/search",
        "cols": 120,
        "repo": ("search", "feat/search", 3, 2),
        "chat": [("user", "review the search branch before I open the PR"),
                 ("claude", "Two findings: an unescaped query string and a missing index.")],
        "data": {
            "session_name": "search-review", "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "medium"}, "agent": {"name": "reviewer"},
            "vim": {"mode": "INSERT"}, "output_style": {"name": "Explanatory"},
            "workspace": {"git_worktree": "search", "added_dirs": ["/srv/shared"]},
            "context_window": {"used_percentage": 41, "context_window_size": 200000,
                               "total_input_tokens": 82000, "total_output_tokens": 3900},
            "cost": {"total_cost_usd": 3.02, "total_duration_ms": 37 * 60000,
                     "total_lines_added": 18, "total_lines_removed": 4},
            "rate_limits": {"five_hour": {"used_percentage": 33, "resets_at": 2 * HOUR + 2400},
                            "seven_day": {"used_percentage": 14, "resets_at": 90 * HOUR}},
        },
    },
    {
        "file": "narrow",
        "title": "~/my-app",
        "cols": 80,
        "repo": ("my-app", "main", 0, 2),
        "chat": [("user", "fix the login redirect loop"),
                 ("claude", "Fixed: the session cookie was set after the redirect.")],
        "data": None,  # same session as "everyday"
    },
]

SGR = re.compile(r"\x1b\[([0-9;]*)m")
COLOURS = {"31": "r", "32": "g", "33": "y", "34": "b", "35": "m", "36": "c"}


def ansi_to_html(text):
    """Turn the statusline's SGR codes (reset, bold, dim, 31-36) into spans."""
    out, pos, fg, bold, dim = [], 0, None, False, False

    def emit(chunk):
        if not chunk:
            return
        cls = [c for c in (fg and "fg-" + fg, bold and "b", dim and "d") if c]
        esc = html.escape(chunk)
        out.append(f'<span class="{" ".join(cls)}">{esc}</span>' if cls else esc)

    for m in SGR.finditer(text):
        emit(text[pos:m.start()])
        pos = m.end()
        for code in (m.group(1) or "0").split(";"):
            if code == "0":
                fg, bold, dim = None, False, False
            elif code == "1":
                bold = True
            elif code == "2":
                dim = True
            elif code in COLOURS:
                fg = COLOURS[code]
    emit(text[pos:])
    return "".join(out)


def make_repo(base, name, branch, staged, modified):
    repo = base / name
    repo.mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q", "-b", branch)
    for i in range(max(modified, 1)):
        (repo / f"file{i}.txt").write_text("v1\n")
    git("add", ".")
    git("-c", "user.name=demo", "-c", "user.email=demo@example.com", "commit", "-qm", "init")
    for i in range(modified):
        (repo / f"file{i}.txt").write_text("v2\n")
    for i in range(staged):
        (repo / f"new{i}.txt").write_text("new\n")
        git("add", f"new{i}.txt")
    return repo


def render_statusline(data, repo, cols, home):
    now = int(time.time())
    data = json.loads(json.dumps(data))
    for window in (data.get("rate_limits") or {}).values():
        window["resets_at"] += now + 30  # offsets are relative; +30s so minutes don't round down
    data["workspace"] = {**data.get("workspace", {}), "current_dir": str(repo), "project_dir": str(repo)}
    # Each scene gets its own config dir, so scenes don't share rate-limit readings.
    env = {**os.environ, "COLUMNS": str(cols), "HOME": str(home), "XDG_CACHE_HOME": str(home / "cache"),
           "CLAUDE_CONFIG_DIR": str(repo)}
    result = subprocess.run(["bash", str(ROOT / "statusline.sh")], input=json.dumps(data),
                            capture_output=True, text=True, env=env, check=True)
    return result.stdout.rstrip("\n").split("\n")


def page(scene, lines):
    cols = scene["cols"]
    chat = "".join(
        f'<div class="row"><span class="fg-d">&gt;</span> <span class="user">{html.escape(t)}</span></div>'
        if who == "user" else
        f'<div class="row"><span class="dot">●</span> {html.escape(t)}</div>'
        for who, t in scene["chat"])
    status = "".join(f'<div class="row sl">{ansi_to_html(l)}</div>' for l in lines)
    return f"""<!doctype html><meta charset="utf-8"><style>
html, body {{ margin: 0; background: transparent; }}
body {{ padding: {MARGIN}px; display: inline-block; }}
.win {{ width: {cols * CELL + 2 * PAD}px; background: #17191e; border: 1px solid #2b2f37;
  border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.35); overflow: hidden;
  font: {FONT}px/{LINE}px 'JetBrains Mono', 'DejaVu Sans Mono', 'FreeMono', monospace; color: #c9ced6; }}
.top {{ height: {TITLE}px; display: flex; align-items: center; padding: 0 14px; background: #1e2127;
  border-bottom: 1px solid #2b2f37; position: relative; }}
.top i {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }}
.top span {{ position: absolute; left: 0; right: 0; text-align: center; color: #7d8590; font-size: 12px; }}
.body {{ padding: {PAD}px; }}
.row {{ height: {LINE}px; white-space: pre; overflow: hidden; }}
.user {{ color: #e6e9ee; }}
.dot {{ color: #d97757; }}
.chat {{ margin-bottom: 12px; }}
.input {{ border: 1px solid #3a3f4b; border-radius: 6px; padding: 6px 10px; margin-bottom: 8px; }}
.cursor {{ display: inline-block; width: {CELL}px; height: 16px; background: #c9ced6; vertical-align: -3px; }}
.sl {{ padding-left: {CELL}px; }}
.foot {{ color: #7d8590; padding-left: {CELL}px; }}
.foot b {{ color: #b392f0; font-weight: normal; }}
.fg-r {{ color: #f97583; }} .fg-g {{ color: #85e89d; }} .fg-y {{ color: #ffd33d; }}
.fg-b {{ color: #79b8ff; }} .fg-m {{ color: #d2a8ff; }} .fg-c {{ color: #56d4dd; }}
.fg-d, .d {{ color: #6e7681; }} .b {{ font-weight: 700; }}
</style>
<div class="win">
  <div class="top"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><span>{html.escape(scene["title"])} — claude</span></div>
  <div class="body">
    <div class="chat">{chat}</div>
    <div class="input"><div class="row"><span class="fg-d">&gt;</span> <span class="cursor"></span></div></div>
    {status}
    <div class="row foot"><b>▸▸ auto mode on</b> (shift+tab to cycle)</div>
  </div>
</div>"""


def trim_png(path, pad):
    """Crop a Chromium RGBA screenshot to its non-transparent pixels plus pad.

    Headless Chromium keeps part of the window for browser UI, so pages are
    rendered into an oversized viewport and trimmed here instead.
    """
    data = path.read_bytes()
    pos, chunks = 8, []
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunks.append((kind, data[pos + 8:pos + 8 + n]))
        pos += 12 + n
    w, h, depth, ctype = struct.unpack(">IIBB", chunks[0][1][:10])
    assert depth == 8 and ctype == 6, "expected 8-bit RGBA"
    raw = zlib.decompress(b"".join(c for k, c in chunks if k == b"IDAT"))
    stride, rows, prev = w * 4, [], bytearray(w * 4)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b, c = prev[i], prev[i - 4] if i >= 4 else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    ys = [y for y in range(h) if any(rows[y][3::4])]
    xs = [x for x in range(w) if any(rows[y][x * 4 + 3] for y in ys)]
    x0, x1 = max(xs[0] - pad, 0), min(xs[-1] + pad + 1, w)
    y0, y1 = max(ys[0] - pad, 0), min(ys[-1] + pad + 1, h)
    body = b"".join(b"\0" + bytes(rows[y][x0 * 4:x1 * 4]) for y in range(y0, y1))

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", x1 - x0, y1 - y0, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(body, 9)) + chunk(b"IEND", b""))
    return x1 - x0, y1 - y0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    everyday = next(s for s in SCENES if s["file"] == "everyday")["data"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for scene in SCENES:
            repo = make_repo(tmp / scene["file"], *scene["repo"])
            lines = render_statusline(scene["data"] or everyday, repo, scene["cols"], tmp / "home")
            src = tmp / f"{scene['file']}.html"
            src.write_text(page(scene, lines), encoding="utf-8")
            png = OUT / f"{scene['file']}.png"
            subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            f"--force-device-scale-factor={SCALE}", "--default-background-color=00000000",
                            f"--window-size={int(scene['cols'] * CELL) + 300},700", f"--screenshot={png}",
                            src.as_uri()], check=True, capture_output=True)
            w, h = trim_png(png, MARGIN * SCALE // 2)
            print(f"{png.relative_to(ROOT)}  {w}x{h}")


if __name__ == "__main__":
    main()
