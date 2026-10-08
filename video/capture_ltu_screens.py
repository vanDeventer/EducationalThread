#!/usr/bin/env python3
"""Capture screenshots of the running web server for the LTU walkthrough video.

    go run ./cmd/edthread serve -addr 127.0.0.1:8088 &
    python3 video/capture_ltu_screens.py        # -> video/out/screens/*.png

Each page is fetched from the server (POSTing the consent form where needed),
the rows the narration talks about are highlighted, and headless Chrome takes
a 2x screenshot.
"""

import os
import pathlib
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out" / "screens"
BASE = os.environ.get("EDTHREAD_URL", "http://127.0.0.1:8088")
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
LTU = "https://w3id.org/edthread/ltu/"

HIGHLIGHT_CSS = """<style>
:root { --bg: #f6f4ef !important; --ink: #1e2430 !important; --muted: #6b7280 !important;
        --card: #ffffff !important; --line: #d8d4ca !important; }  /* light theme regardless of the OS */
tr.hl td { background: #fff1c2 !important; }
tr.hl td:first-child { box-shadow: inset 5px 0 0 #d97a1e; }
details.sparql { display: none; }
</style>"""

# name, path, form fields (POST) or None (GET), rows to highlight (regex), window height
def q(path, **params):
    return path + "?" + urllib.parse.urlencode(params) if params else path


PAGES = [
    ("home", "/", None, None, 1180),
    ("student", q("/q/1-student-where-used", course=LTU + "course/M0066M"),
     None, r"Modelling and Control|Dynamic Systems", 1500),
    ("advisor", "/q/3-advisor-readiness",
     {"target": LTU + "course/R0004E", "wallet": "ltu-student-k.json"}, r"NOT MET", 1320),
    ("advisor-refused", "/q/3-advisor-readiness",
     {"target": LTU + "course/R0004E", "wallet": "student-s.json"}, None, 900),
    ("teacher-cross", q("/q/9-teacher-syllabus-check", course=LTU + "course/R0004E"), None, r"S0004E", 1000),
    ("teacher", q("/q/9-teacher-syllabus-check", course=LTU + "course/M0018M"), None, r"not in programme", 900),
    ("shared", q("/q/10-advisor-shared-courses", **{"from": LTU + "program-TCTEA", "to": LTU + "program-TCDAA"}),
     None, r"Calculus 1|Introduction to Programming", 1750),
    ("switch", "/q/11-advisor-programme-switch",
     {"pathway": LTU + "program-TCDAA-industrial-computer-systems", "wallet": "ltu-student-third-year.json"},
     r"covered by equivalent", 2350),
    ("same-outcomes", q("/q/12-teacher-same-outcomes", course=LTU + "course/S0001E"), None, r"S0004E", 900),
    ("employer", q("/q/7-employer-topic-profile", pathway=LTU + "program-TCTEA-electronic-systems-control"),
     None, r"Automatic Control", 1180),
    ("employer-tcdaa", q("/q/7-employer-topic-profile", pathway=LTU + "program-TCDAA-industrial-computer-systems"),
     None, r"Computer Engineering|Computer Science", 1180),
]


def fetch(path, form):
    if form is None:
        return urllib.request.urlopen(BASE + path).read().decode()
    boundary = uuid.uuid4().hex
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in form.items()) + f"--{boundary}--\r\n"
    req = urllib.request.Request(BASE + path, data=body.encode(),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        return urllib.request.urlopen(req).read().decode()
    except urllib.error.HTTPError as e:  # refusals come back as 403 pages
        return e.read().decode()


def mark(html, pattern):
    if not pattern:
        return html
    return re.sub(r"<tr>(.*?)</tr>",
                  lambda m: (f'<tr class="hl">{m.group(1)}</tr>' if re.search(pattern, m.group(1)) else m.group(0)),
                  html, flags=re.S)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, path, form, pattern, height in PAGES:
            html = mark(fetch(path, form), pattern)
            html = html.replace("<head>", f'<head><base href="{BASE}/">{HIGHLIGHT_CSS}', 1)
            page = pathlib.Path(tmp) / f"{name}.html"
            page.write_text(html)
            png = OUT / f"{name}.png"
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=2", f"--window-size=1440,{height}",
                            f"--screenshot={png}", page.as_uri()],
                           check=True, capture_output=True)
            print(png.relative_to(HERE.parent))


if __name__ == "__main__":
    main()
