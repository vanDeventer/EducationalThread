#!/usr/bin/env python3
"""Render the Educational Thread introduction video (narrated slides).

Requires macOS (for the `say` voice) and:  pip install -r video/requirements.txt

    python3 video/make_video.py            # -> video/out/educational-thread-intro.mp4
    VOICE="Daniel" python3 video/make_video.py

Each scene is a list of build steps. Every step has one narration line; the
step is shown for exactly as long as its narration lasts, so picture and voice
stay in sync. Captions are written as an .srt file and embedded in the mp4.
"""

import os
import pathlib
import re
import subprocess
import tempfile
import wave

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
NAME = "educational-thread-intro"

W, H, S, FPS = 1920, 1080, 2, 30      # S: supersampling factor for smooth edges
VOICE = os.environ.get("VOICE", "Ava (Premium)")
RATE = os.environ.get("RATE", "182")
FADE = 0.35                           # crossfade between builds, seconds
LEAD, TAIL, SCENE_PAUSE = 0.25, 0.45, 0.5

AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
WEIGHT = {"regular": 7, "medium": 5, "demi": 2, "bold": 0}

BG, INK, MUTED = "#F6F4EF", "#1E2430", "#6B7280"
CARD, LINE = "#FFFFFF", "#D8D4CA"
FAINT_TXT, FAINT_LINE = "#B9BCC4", "#E6E2DA"
THREAD = "#8C96A8"
GOOD, BAD = "#13987A", "#C9364F"
ROLE = {
    "student": "#2F6FDE",
    "advisor": "#13987A",
    "teacher": "#D97A1E",
    "admissions": "#8B57D6",
    "employer": "#C43D5C",
}


def tint(hex_color, amount=0.86):
    """Mix a colour with the background (amount = share of background)."""
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - amount) + y * amount):02x}" for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Drawing helpers (logical 1920x1080 coordinates)
# ---------------------------------------------------------------------------

_fonts = {}


def font(size, weight="regular"):
    key = (size, weight)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(AVENIR, int(size * S), index=WEIGHT[weight])
    return _fonts[key]


class Canvas:
    def __init__(self):
        self.img = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def text(self, x, y, s, size=32, weight="regular", fill=INK, anchor="la"):
        self.d.text((x * S, y * S), s, font=font(size, weight), fill=fill, anchor=anchor)

    def tw(self, s, size=32, weight="regular"):
        return self.d.textlength(s, font=font(size, weight)) / S

    def wrap(self, s, size, weight, maxw):
        lines, cur = [], ""
        for word in s.split():
            t = f"{cur} {word}".strip()
            if cur and self.tw(t, size, weight) > maxw:
                lines.append(cur)
                cur = word
            else:
                cur = t
        return lines + [cur] if cur else lines

    def para(self, x, y, s, size=32, weight="regular", fill=INK, maxw=800, lh=1.3, align="left"):
        lines = self.wrap(s, size, weight, maxw)
        for i, ln in enumerate(lines):
            self.text(x, y + i * size * lh, ln, size, weight, fill, "ma" if align == "center" else "la")
        return len(lines) * size * lh

    def para_mid(self, cx, cy, s, size, weight="regular", fill=INK, maxw=400, lh=1.22):
        """Paragraph centred on (cx, cy)."""
        lines = self.wrap(s, size, weight, maxw)
        top = cy - (len(lines) - 1) * size * lh / 2
        for i, ln in enumerate(lines):
            self.text(cx, top + i * size * lh, ln, size, weight, fill, "mm")

    def box(self, x, y, w, h, fill=CARD, outline=LINE, r=16, width=2):
        self.d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S,
                                 fill=fill, outline=outline, width=int(width * S) if outline else 0)

    def circle(self, x, y, r, fill, outline=None, width=2):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill,
                       outline=outline, width=int(width * S))

    def line(self, pts, fill, width=3, dash=None):
        if not dash:
            self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=int(width * S), joint="curve")
            return
        on, off = dash
        pos, drawing = 0.0, True
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            t = 0.0
            while t < seg:
                step = min((on if drawing else off) - pos, seg - t)
                if drawing:
                    a, b = t / seg, (t + step) / seg
                    self.d.line([((x0 + (x1 - x0) * a) * S, (y0 + (y1 - y0) * a) * S),
                                 ((x0 + (x1 - x0) * b) * S, (y0 + (y1 - y0) * b) * S)],
                                fill=fill, width=int(width * S))
                t += step
                pos += step
                if pos >= (on if drawing else off) - 1e-9:
                    pos, drawing = 0.0, not drawing

    def head(self, tip, frm, fill, size=16):
        (x1, y1), (x0, y0) = tip, frm
        dx, dy = x1 - x0, y1 - y0
        n = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / n, dy / n
        bx, by = x1 - ux * size, y1 - uy * size
        pts = [(x1, y1), (bx - uy * size * 0.55, by + ux * size * 0.55), (bx + uy * size * 0.55, by - ux * size * 0.55)]
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill)

    def curve(self, p0, p3, fill, width=3, dash=None, head=0, vertical=False, bulge=None):
        """Cubic Bezier with horizontal (or vertical) tangents, optional arrow head at p3."""
        (x0, y0), (x3, y3) = p0, p3
        if bulge is not None:                       # arc above/below: control points offset in y
            c1, c2 = (x0, y0 + bulge), (x3, y3 + bulge)
        elif vertical:
            dy = (y3 - y0) * 0.5
            c1, c2 = (x0, y0 + dy), (x3, y3 - dy)
        else:
            dx = (x3 - x0) * 0.5
            c1, c2 = (x0 + dx, y0), (x3 - dx, y3)
        pts = []
        for i in range(41):
            t = i / 40
            mt = 1 - t
            pts.append((mt ** 3 * x0 + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * x3,
                        mt ** 3 * y0 + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * y3))
        if head:
            self.line(pts[:-2], fill, width, dash)
            self.head(pts[-1], pts[-4], fill, head)
        else:
            self.line(pts, fill, width, dash)

    def pill(self, x, y, s, fill, color="#FFFFFF", size=22, weight="demi", padx=16, h=None, outline=None):
        h = h or size * 1.75
        w = self.tw(s, size, weight) + 2 * padx
        self.box(x, y, w, h, fill=fill, outline=outline, r=h / 2, width=2)
        self.text(x + w / 2, y + h / 2, s, size, weight, color, "mm")
        return w

    def check(self, x, y, r=16, color=GOOD):
        self.circle(x, y, r, color)
        self.line([(x - r * 0.45, y + r * 0.02), (x - r * 0.1, y + r * 0.38), (x + r * 0.5, y - r * 0.35)], "#FFFFFF", r * 0.22)

    def cross(self, x, y, r=16, color=BAD):
        self.circle(x, y, r, color)
        k = r * 0.38
        self.line([(x - k, y - k), (x + k, y + k)], "#FFFFFF", r * 0.22)
        self.line([(x - k, y + k), (x + k, y - k)], "#FFFFFF", r * 0.22)

    def lock(self, x, y, color):
        self.d.arc([(x - 13) * S, (y - 30) * S, (x + 13) * S, (y - 2) * S], 180, 360, fill=color, width=int(5 * S))
        self.line([(x - 13, y - 16), (x - 13, y - 4)], color, 5)
        self.line([(x + 13, y - 16), (x + 13, y - 4)], color, 5)
        self.box(x - 20, y - 6, 40, 32, fill=color, outline=None, r=6)

    def frame(self):
        return self.img.resize((W, H), Image.LANCZOS)


def chrome(c, scene_no, total):
    c.text(100, 1032, "Educational Thread", 20, "demi", MUTED)
    c.box(0, 1072, W * (scene_no + 1) / total, 8, fill=INK, outline=None, r=0)


def role_header(c, role, question):
    c.pill(100, 56, role.upper(), ROLE[role], size=22)
    c.text(100, 104, question, 50, "bold")


def title(c, s):
    c.text(100, 80, s, 54, "bold")


# ---------------------------------------------------------------------------
# The shared curriculum map
# ---------------------------------------------------------------------------

ODE_UNITS = ["First-order ODEs", "Second-order linear ODEs", "Systems of linear ODEs",
             "Laplace transform", "Stability and phase plane"]
CE_UNITS = ["Modelling dynamic systems", "Transfer functions", "Feedback and stability",
            "State-space models", "PID design project"]
FM_UNITS = ["Conservation laws", "Unsteady tank flow", "Boundary layers"]
SKILLS = [("model", "mathematical modelling"), ("sim", "simulate dynamic systems"),
          ("ctrl", "design control systems"), ("fluid", "analyse fluid flow")]
OCCS = [("ce", "Control engineer"), ("pe", "Process engineer")]

UNIT_LINKS = [("ode1", "ce1", "requires"), ("ode2", "ce1", "requires"), ("ode1", "fm2", "requires"),
              ("ode1", "fm3", "uses"), ("ode3", "ce4", "requires"), ("ode4", "ce2", "requires"),
              ("ode5", "ce3", "uses")]
SKILL_LINKS = [("ce1", "model"), ("ce1", "sim"), ("ce3", "ctrl"), ("ce4", "ctrl"), ("ce5", "ctrl"),
               ("ce5", "sim"), ("fm1", "fluid"), ("fm2", "model"), ("fm3", "fluid")]
OCC_LINKS = [("model", "ce"), ("sim", "ce"), ("ctrl", "ce"), ("model", "pe"), ("fluid", "pe")]


def map_geometry():
    g = {}
    for i in range(5):
        g[f"ode{i + 1}"] = (120, 286 + i * 104, 420, 76)
    for i in range(5):
        g[f"ce{i + 1}"] = (800, 268 + i * 68, 440, 56)
    for i in range(3):
        g[f"fm{i + 1}"] = (800, 708 + i * 68, 440, 56)
    for i, (k, _) in enumerate(SKILLS):
        g[k] = (1350, 262 + i * 92, 270, 70)
    g["ce"] = (1676, 300, 160, 96)
    g["pe"] = (1676, 520, 160, 96)
    return g


GEO = map_geometry()


def right(k):
    x, y, w, h = GEO[k]
    return (x + w, y + h / 2)


def left(k):
    x, y, w, h = GEO[k]
    return (x, y + h / 2)


def draw_map(c, hl=None, color=None, skills=True, threads=True, cards=("ode", "ce", "fm")):
    hl = hl or set()
    focus = bool(hl)

    def style(k):
        if not focus:
            return CARD, LINE, INK, 2
        if k in hl:
            return tint(color, 0.82), color, INK, 3
        return CARD, FAINT_LINE, FAINT_TXT, 2

    def link_style(a, b, kind="requires"):
        dash = (10, 8) if kind == "uses" else None
        if not focus:
            return THREAD, 3, dash
        if a in hl and b in hl:
            return color, 5, dash
        return FAINT_LINE, 3, dash

    # Course cards
    if "ode" in cards:
        c.box(100, 200, 460, 640, fill=tint(INK, 0.95), outline=None, r=22)
        c.text(120, 214, "Ordinary Differential Equations", 26, "bold", INK if not focus else MUTED)
        c.text(120, 250, "year 1", 20, "medium", MUTED)
    if "ce" in cards:
        c.box(780, 200, 480, 412, fill=tint(INK, 0.95), outline=None, r=22)
        c.text(800, 214, "Control Engineering", 26, "bold", INK if not focus else MUTED)
        c.text(1240, 220, "year 2", 20, "medium", MUTED, "ra")
    if "fm" in cards:
        c.box(780, 640, 480, 276, fill=tint(INK, 0.95), outline=None, r=22)
        c.text(800, 654, "Fluid Mechanics", 26, "bold", INK if not focus else MUTED)
        c.text(1240, 660, "year 2", 20, "medium", MUTED, "ra")

    # Threads (drawn under the boxes)
    if threads:
        for a, b, kind in UNIT_LINKS:
            col, wid, dash = link_style(a, b, kind)
            if not (a in hl and b in hl):
                c.curve(right(a), left(b), col, wid, dash, head=14)
        for a, b, kind in UNIT_LINKS:
            col, wid, dash = link_style(a, b, kind)
            if a in hl and b in hl:
                c.curve(right(a), left(b), col, wid, dash, head=16)
    if skills:
        for a, b in SKILL_LINKS + OCC_LINKS:
            col, wid, dash = link_style(a, b)
            if not focus:
                col, wid = tint(THREAD, 0.4), 2
            c.curve(right(a), left(b), col, wid, head=0)

    # Boxes
    names = {f"ode{i + 1}": n for i, n in enumerate(ODE_UNITS)}
    names.update({f"ce{i + 1}": n for i, n in enumerate(CE_UNITS)})
    names.update({f"fm{i + 1}": n for i, n in enumerate(FM_UNITS)})
    for k, name in names.items():
        if k[:2] not in [x[:2] for x in cards]:
            continue
        x, y, w, h = GEO[k]
        fill, outline, txt, wid = style(k)
        c.box(x, y, w, h, fill=fill, outline=outline, r=12, width=wid)
        c.text(x + 20, y + h / 2, name, 26 if k.startswith("ode") else 24, "demi", txt, "lm")
    if skills:
        for k, name in SKILLS:
            x, y, w, h = GEO[k]
            fill, outline, txt, wid = style(k)
            c.box(x, y, w, h, fill=fill, outline=outline, r=35, width=wid)
            c.para_mid(x + w / 2, y + h / 2, name, 21, "demi", txt, maxw=w - 40)
        for k, name in OCCS:
            x, y, w, h = GEO[k]
            fill, outline, txt, wid = style(k)
            if not focus:
                fill, outline = INK, INK
                txt = "#FFFFFF"
            elif k in hl:
                fill, txt = color, "#FFFFFF"
            c.box(x, y, w, h, fill=fill, outline=outline, r=14, width=wid)
            c.para_mid(x + w / 2, y + h / 2, name, 22, "bold", txt, maxw=w - 24)
        c.text(1350, 226, "SKILLS", 18, "bold", MUTED)
        c.text(1676, 264, "OCCUPATIONS", 18, "bold", MUTED)


def legend(c, x, y):
    c.line([(x, y), (x + 60, y)], THREAD, 3)
    c.text(x + 72, y, "requires", 22, "medium", MUTED, "lm")
    c.line([(x + 190, y), (x + 250, y)], THREAD, 3, dash=(10, 8))
    c.text(x + 262, y, "uses", 22, "medium", MUTED, "lm")


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def thread_decoration(c, y, alpha=0.0):
    cols = list(ROLE.values())
    xs = [240 + i * 180 for i in range(9)]
    ys = [y + (34 if i % 2 else -34) for i in range(9)]
    for i in range(8):
        c.curve((xs[i], ys[i]), (xs[i + 1], ys[i + 1]), tint(THREAD, alpha + 0.2), 4)
    for i, (x, yy) in enumerate(zip(xs, ys)):
        c.circle(x, yy, 18, cols[i % 5], outline=BG, width=5)


def s_title(c, step):
    c.text(W / 2, 380, "Educational Thread", 120, "bold", INK, "mm")
    c.text(W / 2, 485, "Following education as a web of digital threads", 44, "medium", MUTED, "mm")
    thread_decoration(c, 720)


QUESTIONS = [
    ("student", "Why am I learning this?"),
    ("advisor", "Is this student ready for the next course?"),
    ("teacher", "Does my course hang together?"),
    ("admissions", "What is this applicant missing?"),
    ("employer", "What does this degree really cover?"),
]


def s_questions(c, step):
    c.text(W / 2, 110, "One course. Five questions.", 58, "bold", INK, "mm")
    c.box(660, 190, 600, 100, fill=INK, outline=None, r=18)
    c.text(W / 2, 240, "Ordinary Differential Equations", 34, "bold", "#FFFFFF", "mm")
    cw, gap = 316, 24
    x0 = (W - (5 * cw + 4 * gap)) / 2
    for i, (role, q) in enumerate(QUESTIONS):
        if step < i + 1:
            continue
        x = x0 + i * (cw + gap)
        c.curve((W / 2, 290), (x + cw / 2, 470), ROLE[role], 4, vertical=True)
        c.box(x, 470, cw, 330, fill=CARD, outline=LINE, r=20)
        c.box(x, 470, cw, 70, fill=ROLE[role], outline=None, r=20)
        c.box(x, 510, cw, 30, fill=ROLE[role], outline=None, r=0)
        c.text(x + cw / 2, 505, role.capitalize(), 30, "bold", "#FFFFFF", "mm")
        c.para(x + cw / 2, 580, f"“{q}”", 34, "demi", INK, maxw=cw - 50, align="center")


STANDARDS = ["schema.org", "Europass Learning Model", "ESCO", "SKOS", "W3C RDF · SPARQL · SHACL",
             "Verifiable Credentials"]


def s_idea(c, step):
    title(c, "The idea: thread the learning outcomes")
    if step == 0:
        draw_map(c, cards=("ode",), skills=False, threads=False)
        x, y, w, h = GEO["ode4"]
        c.box(x, y, w, h, fill=tint(INK, 0.85), outline=INK, r=12, width=3)
        c.text(x + 20, y + h / 2, ODE_UNITS[3], 26, "demi", INK, "lm")
        c.curve((x + w, y + h / 2), (700, 520), INK, 3, head=0)
        cx, cy, cw = 700, 250, 900
        c.box(cx, cy, cw, 600, fill=CARD, outline=INK, r=22, width=3)
        c.text(cx + 40, cy + 36, "Learning unit", 22, "bold", MUTED)
        c.text(cx + 40, cy + 70, "Laplace transform", 44, "bold")
        fields = [("TOPIC", "Laplace transform  (MSC 44A10)"),
                  ("LEARNING OUTCOME", "Solve initial-value problems with the Laplace transform"),
                  ("ACTIVITIES", "Lectures · computer lab"),
                  ("ASSESSMENT", "Written exam · lab report")]
        for i, (k, v) in enumerate(fields):
            fy = cy + 170 + i * 105
            c.text(cx + 40, fy, k, 20, "bold", ROLE["student"] if i == 1 else MUTED)
            c.para(cx + 40, fy + 30, v, 32, "demi" if i == 1 else "medium", INK, maxw=cw - 80)
        return
    draw_map(c, skills=step >= 2)
    legend(c, 120, 880)
    if step >= 3:
        widths = [c.tw(s, 24, "demi") + 32 for s in STANDARDS]
        x = (W - (sum(widths) + 16 * (len(STANDARDS) - 1))) / 2
        c.text(W / 2, 950, "Built on open standards", 22, "bold", MUTED, "mm")
        for s, wd in zip(STANDARDS, widths):
            c.pill(x, 975, s, INK, size=24)
            x += wd + 16


def s_student(c, step):
    role_header(c, "student", "Why am I learning the Laplace transform?")
    hl = {"ode4"}
    if step >= 1:
        hl |= {"ce2", "ce3", "ce5", "ode1", "fm2"}
    if step >= 2:
        hl |= {"ctrl", "model", "ce", "pe"}
    draw_map(c, hl=hl, color=ROLE["student"], skills=True)
    x, y, w, h = GEO["ode4"]
    c.pill(x + w - 150, y - 18, "you are here", ROLE["student"], size=18, h=30)
    if step >= 1:
        legend(c, 120, 880)


ADVISOR_ROWS = [
    (True, "Calculus", "Differentiate elementary functions"),
    (True, "Calculus", "Evaluate integrals"),
    (True, "Linear Algebra", "Solve linear systems"),
    (True, "Linear Algebra", "Compute eigenvalues and eigenvectors"),
    (True, "ODE", "Solve first-order ODEs"),
    (True, "ODE", "Formulate first-order ODE models"),
    (True, "ODE", "Solve second-order linear ODEs"),
    (False, "ODE", "Solve systems x' = Ax"),
    (False, "ODE", "Solve IVPs with the Laplace transform"),
    (False, "ODE", "Classify equilibria, phase portraits"),
]


def consent_card(c, x, y, w, rows, color):
    c.box(x, y, w, 90 + 46 * len(rows), fill=CARD, outline=color, r=20, width=3)
    c.lock(x + 46, y + 44, color)
    c.text(x + 84, y + 36, "Shared with consent", 30, "bold", color, "lm")
    for i, (k, v) in enumerate(rows):
        c.text(x + 36, y + 96 + i * 46, k, 22, "bold", MUTED, "lm")
        c.text(x + 190, y + 96 + i * 46, v, 24, "medium", INK, "lm")


def s_advisor(c, step):
    role_header(c, "advisor", "Is this student ready for Control Engineering?")
    col = ROLE["advisor"]
    consent_card(c, 1240, 210, 580, [("Learner", "did:example:…3a91"), ("With", "Study advisors"),
                                     ("Purpose", "academic advising"), ("Until", "30 June 2027")], col)
    if step >= 1:
        c.text(100, 222, "PREREQUISITES, INCLUDING INDIRECT ONES", 20, "bold", MUTED)
        for i, (met, course, outcome) in enumerate(ADVISOR_ROWS):
            y = 260 + i * 66
            c.box(100, y, 1080, 56, fill=CARD if met else tint(BAD, 0.88),
                  outline=LINE if met else BAD, r=12, width=2)
            (c.check if met else c.cross)(132, y + 28, 15)
            c.text(166, y + 28, course, 22, "demi", MUTED, "lm")
            c.text(370, y + 28, outcome, 26, "demi", INK, "lm")
            c.text(1160, y + 28, "met" if met else "not met", 22, "bold", GOOD if met else BAD, "rm")
    if step >= 2:
        y = 520
        c.box(1240, y, 580, 330, fill=tint(col, 0.85), outline=col, r=20, width=3)
        c.text(1276, y + 40, "Advice", 30, "bold", col, "lm")
        c.para(1276, y + 72, "Complete three ODE units before Control Engineering:", 26, "demi", INK, maxw=510)
        for i, (u, hrs) in enumerate([("Systems of linear ODEs", 45), ("Laplace transform", 40),
                                      ("Stability and phase plane", 35)]):
            yy = y + 178 + i * 46
            c.circle(1290, yy, 6, col)
            c.text(1310, yy, u, 26, "medium", INK, "lm")
            c.text(1790, yy, f"{hrs} h", 24, "demi", MUTED, "rm")


TIMELINE = [("First-order ODEs", 1, 3), ("Second-order linear ODEs", 3, 4), ("Laplace transform", 4, 6),
            ("Stability and phase plane", 6, 7), ("Systems of linear ODEs", 7, 9)]


def s_teacher(c, step):
    role_header(c, "teacher", "Does my course hang together?")
    col = ROLE["teacher"]
    c.text(160, 222, "ODE · AUTUMN 2026 · AS TAUGHT", 20, "bold", MUTED)
    x0, ww, top, bh = 160, 200, 300, 170
    c.line([(x0, top + bh + 30), (x0 + 8 * ww, top + bh + 30)], LINE, 3)
    for wk in range(1, 9):
        c.text(x0 + (wk - 1) * ww + ww / 2, top + bh + 60, f"week {wk}", 20, "medium", MUTED, "mm")
    for name, s, e in TIMELINE:
        x, w = x0 + (s - 1) * ww + 6, (e - s) * ww - 12
        flagged = step >= 1 and name in ("Stability and phase plane", "Systems of linear ODEs")
        c.box(x, top, w, bh, fill=tint(BAD, 0.88) if flagged else tint(col, 0.84),
              outline=BAD if flagged else col, r=14, width=3)
        c.para_mid(x + w / 2, top + bh / 2, name, 26, "demi", INK, maxw=w - 28)
    if step >= 1:
        a = (x0 + 5 * ww + ww / 2, top)
        b = (x0 + 6 * ww + ww, top)
        c.curve(a, (b[0], b[1] - 4), BAD, 5, head=18, bulge=-70)
        c.text(x0 + 6 * ww + 40, top - 76, "requires — but is taught later", 24, "bold", BAD, "lm")
    if step >= 2:
        y = 640
        c.box(160, y, 1600, 270, fill=CARD, outline=BAD, r=20, width=3)
        c.pill(196, y + 30, "NEVER ASSESSED", BAD, size=20)
        c.text(196, y + 104, "Formulate first-order ODE models from rate-of-change descriptions", 34, "bold", INK, "lm")
        cols = [("PRACTISED IN", "Modelling workshop, week 1", INK),
                ("ASSESSED BY", "nothing", BAD),
                ("NEEDED LATER BY", "Control Engineering · Fluid Mechanics", INK)]
        for (k, v, fc), cx in zip(cols, (196, 640, 1000)):
            c.text(cx, y + 168, k, 20, "bold", MUTED)
            c.para(cx, y + 198, v, 28, "demi", fc, maxw=720)


ADM_LEFT = [("MA101", "Differentiate and integrate functions of one variable"),
            ("MA101", "Solve linear systems and compute eigenvalues"),
            ("MA201", "Solve separable and linear first-order ODEs"),
            ("MA201", "Solve second-order linear ODEs")]
ADM_RIGHT = [("Calculus", "Differentiation", 0, None), ("Calculus", "Integration", 0, None),
             ("Linear Algebra", "Matrices and linear systems", 1, None),
             ("Linear Algebra", "Eigenvalues", 1, None),
             ("ODE", "First-order ODEs: solving", 2, None),
             ("ODE", "First-order ODEs: modelling", None, 40),
             ("ODE", "Second-order linear ODEs", 3, None),
             ("ODE", "Systems of linear ODEs", None, 45),
             ("ODE", "Laplace transform", None, 40)]


def s_admissions(c, step):
    role_header(c, "admissions", "What is this applicant missing for year 2?")
    col = ROLE["admissions"]
    c.text(100, 222, "APPLICANT’S CREDENTIALS · OTHER UNIVERSITY", 20, "bold", MUTED)
    lcards = []
    for i, (code, txt) in enumerate(ADM_LEFT):
        y = 258 + i * 132
        c.box(100, y, 560, 118, fill=CARD, outline=col, r=16, width=2)
        c.text(126, y + 20, code, 20, "bold", col)
        c.para(126, y + 46, txt, 25, "demi", INK, maxw=510)
        lcards.append((660, y + 59))
    rrows = []
    if step >= 1:
        c.text(1100, 222, "NEEDED FROM OUR YEAR 1", 20, "bold", MUTED)
        for i, (course, unit, src, hrs) in enumerate(ADM_RIGHT):
            y = 258 + i * 70
            missing = src is None and step >= 2
            c.box(1100, y, 720, 58, fill=tint(BAD, 0.88) if missing else CARD,
                  outline=BAD if missing else LINE, r=12, width=2)
            c.text(1124, y + 29, course, 20, "demi", MUTED, "lm")
            c.text(1290, y + 29, unit, 25, "demi", INK, "lm")
            if src is not None:
                c.check(1790, y + 29, 14)
                c.curve(lcards[src], (1100, y + 29), GOOD, 3, head=12)
            elif missing:
                c.text(1735, y + 29, f"{hrs} h", 22, "bold", BAD, "rm")
                c.cross(1790, y + 29, 14)
            rrows.append(y)
    if step < 2:
        consent_card(c, 100, 800, 560, [("Purpose", "admission assessment"), ("Until", "31 January 2027")], col)
    else:
        c.box(100, 800, 560, 190, fill=tint(col, 0.85), outline=col, r=20, width=3)
        c.text(130, 838, "Bridging needed", 28, "bold", col, "lm")
        c.text(130, 902, "3 units · 125 h", 50, "bold", INK, "lm")
        c.text(130, 958, "not a whole course — just the right blocks", 22, "medium", MUTED, "lm")


SKILL_ROWS = [("design control systems", "create", 6, "written exam · lab report · project", "Control engineer"),
              ("simulate dynamic systems", "create", 6, "written exam · lab report · project", "Control engineer"),
              ("mathematical modelling", "apply", 3, "written exam · lab report", "Control engineer, Process engineer"),
              ("analyse fluid flow", "apply", 3, "written exam", "Process engineer")]


def s_employer(c, step):
    role_header(c, "employer", "What does this degree really cover?")
    col = ROLE["employer"]
    if step == 0:
        x, y, w, h = 410, 260, 1100, 560
        c.box(x, y, w, h, fill=CARD, outline=INK, r=10, width=3)
        c.box(x + 18, y + 18, w - 36, h - 36, fill=None, outline=LINE, r=6, width=2)
        c.text(W / 2, y + 100, "Example Institute of Technology", 28, "medium", MUTED, "mm")
        c.text(W / 2, y + 180, "Bachelor of Science in", 34, "medium", INK, "mm")
        c.para(W / 2, y + 230, "Intelligent Cyber-Physical Systems Engineering", 58, "bold", INK, maxw=900,
               align="center")
        c.circle(x + w - 40, y + 40, 56, col)
        c.text(x + w - 40, y + 38, "?", 72, "bold", "#FFFFFF", "mm")
        return
    c.box(100, 200, 1720, 80, fill=INK, outline=None, r=16)
    c.text(W / 2, 240, "BSc in Intelligent Cyber-Physical Systems Engineering", 32, "bold", "#FFFFFF", "mm")
    heads = [(100, "SKILL"), (620, "HIGHEST LEVEL (BLOOM)"), (1040, "HOW IT WAS ASSESSED"), (1470, "NEEDED BY")]
    for x, hname in heads:
        c.text(x + 24, 330, hname, 20, "bold", MUTED)
    for i, (skill, lvl, rank, ev, occ) in enumerate(SKILL_ROWS):
        y = 370 + i * 140
        c.box(100, y, 1720, 120, fill=CARD, outline=LINE, r=16)
        c.para(124, y + 28, skill, 30, "bold", INK, maxw=470)
        for k in range(6):
            c.box(644 + k * 54, y + 30, 46, 22, fill=col if k < rank else tint(col, 0.85), outline=None, r=6)
        c.text(644, y + 84, f"{lvl}  ({rank} of 6)", 24, "demi", INK, "lm")
        c.para(1064, y + 28, ev, 26, "medium", INK, maxw=380)
        c.para(1494, y + 28, occ, 26, "demi", INK, maxw=300)


def s_privacy(c, step):
    title(c, "Privacy by design")
    # Public graph
    c.box(100, 190, 1720, 290, fill=CARD, outline=INK, r=22, width=3)
    c.pill(130, 210, "PUBLIC", INK, size=20)
    c.text(250, 228, "Curriculum graph — courses, units, outcomes, skills. No personal data.", 28, "demi", INK, "lm")
    nodes = [(260, 380), (420, 320), (560, 410), (720, 330), (880, 400), (1040, 320), (1200, 410),
             (1360, 330), (1520, 400), (1680, 340)]
    for a, b in zip(nodes, nodes[1:]):
        c.line([a, b], THREAD, 3)
    for a, b in [(0, 2), (3, 5), (4, 6), (6, 8)]:
        c.line([nodes[a], nodes[b]], tint(THREAD, 0.5), 2)
    for i, (x, y) in enumerate(nodes):
        c.circle(x, y, 18, list(ROLE.values())[i % 5], outline=CARD, width=4)
    # Learner wallet
    col = ROLE["student"]
    c.box(100, 600, 640, 380, fill=tint(col, 0.88), outline=col, r=22, width=3)
    c.pill(130, 620, "PRIVATE", col, size=20)
    c.text(258, 638, "The learner’s wallet", 28, "demi", INK, "lm")
    c.text(130, 700, "did:example:student-s-3a91", 24, "demi", MUTED, "lm")
    creds = ["Calculus · integration", "ODE · first-order models", "Linear Algebra · eigenvalues"]
    for i, cr in enumerate(creds):
        y = 740 + i * 74
        c.box(130, y, 580, 60, fill=CARD, outline=LINE, r=12)
        c.check(162, y + 30, 14)
        c.text(192, y + 30, cr, 24, "demi", INK, "lm")
    for x, n in zip((250, 420, 590), (0, 2, 3)):
        nx, ny = nodes[n]
        c.curve((x, 600), (nx, ny + 24), col, 3, head=14, vertical=True)
    c.para(780, 520, "Achievements point into the public graph — never the other way round.", 24,
           "demi", col, maxw=380)
    if step >= 1:
        c.box(1180, 600, 640, 170, fill=CARD, outline=ROLE["advisor"], r=20, width=3)
        c.lock(1226, 650, ROLE["advisor"])
        c.text(1266, 642, "Consent", 30, "bold", ROLE["advisor"], "lm")
        c.text(1210, 700, "who · for what purpose · until when", 26, "demi", INK, "lm")
        c.text(1210, 740, "pseudonymous: no name, no ID number", 22, "medium", MUTED, "lm")
        c.curve((740, 690), (1180, 685), ROLE["advisor"], 4, head=16)
    if step >= 2:
        c.box(1180, 800, 640, 180, fill=CARD, outline=INK, r=20, width=3)
        c.text(1210, 836, "Course statistics", 30, "bold", INK, "lm")
        c.text(1210, 880, "aggregates only · small groups suppressed", 24, "demi", INK, "lm")
        for k, hgt in enumerate([40, 64, 52, 30, 58]):
            c.box(1210 + k * 44, 960 - hgt, 30, hgt, fill=THREAD, outline=None, r=4)
        c.text(1440, 940, "groups under 10: not shown", 22, "medium", MUTED, "lm")


def s_close(c, step):
    c.text(W / 2, 360, "Educational Thread", 110, "bold", INK, "mm")
    c.text(W / 2, 460, "One web of learning. Many questions answered.", 44, "medium", MUTED, "mm")
    names = [r.capitalize() for r in ROLE]
    widths = [c.tw(n, 26, "demi") + 36 for n in names]
    x = (W - (sum(widths) + 20 * 4)) / 2
    for n, wd, colr in zip(names, widths, ROLE.values()):
        c.pill(x, 560, n, colr, size=26, padx=18)
        x += wd + 20
    thread_decoration(c, 790)


SCENES = [
    (s_title, [
        "Every course is part of a longer story. Educational Thread makes that story visible: "
        "across courses, programs, institutions, and jobs.",
    ]),
    (s_questions, [
        "Take one course: differential equations. Five people, five questions.",
        "The student: why am I learning this?",
        "The advisor: is this student ready for the next course?",
        "The teacher: does my course hang together?",
        "Admissions: what is this applicant missing?",
        "And the employer: what does this degree really cover?",
    ]),
    (s_idea, [
        "The idea: split each course into learning units, each with a topic, learning outcomes, "
        "activities, and an assessment.",
        "Then link the outcomes across courses. This one requires that one, or uses it. That is the thread.",
        "Outcomes connect to skills, and skills to occupations.",
        "And it is all built on open standards, such as schema dot org, the Europass Learning Model, and ESCO.",
    ]),
    (s_student, [
        "A student struggling with the Laplace transform asks why it matters.",
        "Control Engineering needs it for transfer functions and feedback design. "
        "First-order equations return in Fluid Mechanics.",
        "And the thread leads on to real jobs: control engineer, process engineer.",
    ]),
    (s_advisor, [
        "An advisor asks if a student is ready for Control Engineering. The student shares their "
        "record, for advising only.",
        "Every prerequisite, even indirect ones: seven met, three not.",
        "So the advice is concrete: complete these three units first.",
    ]),
    (s_teacher, [
        "A teacher sees the course as it is actually taught this autumn.",
        "The thread spots a problem: stability comes before the systems it depends on.",
        "And an outcome that is practised, but never assessed, although two later courses rely on it.",
    ]),
    (s_admissions, [
        "Admissions reviews an applicant from another university, who shares their credentials for "
        "this assessment only.",
        "Outcomes that match ours are credited.",
        "What is missing is precise: three units, about one hundred and twenty-five hours. "
        "Not a whole course.",
    ]),
    (s_employer, [
        "An employer sees a degree with an impressive name. But what does it cover?",
        "The skills behind the name, the level reached, how each was assessed, and who needs them.",
    ]),
    (s_privacy, [
        "Personal records stay in the learner's own wallet. They point into the public curriculum, "
        "never the other way round.",
        "They are shared only with consent: who, for what, and until when. Learners appear as pseudonyms.",
        "And course statistics are published only as aggregates.",
    ]),
    (s_close, [
        "Educational Thread. One web of learning, from a first course, through continuing "
        "education, and into working life.",
    ]),
]


# ---------------------------------------------------------------------------
# Audio, captions, assembly
# ---------------------------------------------------------------------------

def speak(text, path):
    subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(path), "--file-format=WAVE",
                    "--data-format=LEI16@24000", text], check=True)
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate(), w.readframes(w.getnframes())


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def sentences(text):
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s]


def build(scenes, name, chrome_fn=None):
    """Render scenes [(draw_fn, [narration per step]), ...] to video/out/<name>.mp4 (+ .srt)."""
    chrome_fn = chrome_fn or chrome
    OUT.mkdir(exist_ok=True)
    frames_dir = OUT / f"frames-{name}"
    frames_dir.mkdir(exist_ok=True)
    rate, silence = 24000, lambda sec: b"\x00\x00" * int(rate * sec)

    segments, audio, captions, t = [], [], [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for si, (fn, lines) in enumerate(scenes):
            for step, text in enumerate(lines):
                c = Canvas()
                fn(c, step)
                chrome_fn(c, si, len(scenes))
                img = c.frame()
                img.save(frames_dir / f"{si + 1:02}-{step + 1}.png")

                dur, pcm = speak(text, pathlib.Path(tmp) / "seg.wav")
                tail = TAIL + (SCENE_PAUSE if step == len(lines) - 1 else 0)
                audio += [silence(LEAD), pcm, silence(tail)]

                start, total_chars = t + LEAD, len(text)
                for sent in sentences(text):
                    d = dur * len(sent) / total_chars
                    captions.append((start, start + d, sent))
                    start += d

                length = LEAD + dur + tail
                segments.append((img, t, t + length))
                t += length
                print(f"scene {si + 1} step {step + 1}: {length:5.1f}s")

    wav = OUT / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(audio))

    srt = OUT / f"{name}.srt"
    srt.write_text("\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{s}\n"
                             for i, (a, b, s) in enumerate(captions, 1)))

    mp4 = OUT / f"{name}.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-i", str(srt),
           "-map", "0:v", "-map", "1:a", "-map", "2:s",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-tune", "stillimage",
           "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
           "-movflags", "+faststart", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev, fade_n = None, int(FADE * FPS)
    for img, a, b in segments:
        n = round(b * FPS) - round(a * FPS)
        raw = img.tobytes()
        for k in range(n):
            if prev is not None and k < fade_n:
                proc.stdin.write(Image.blend(prev, img, (k + 1) / (fade_n + 1)).tobytes())
            else:
                proc.stdin.write(raw)
        prev = img
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    wav.unlink()
    print(f"\n{mp4}  ({int(t // 60)}:{t % 60:04.1f})\n{srt}")


def main():
    build(SCENES, NAME)


if __name__ == "__main__":
    main()
