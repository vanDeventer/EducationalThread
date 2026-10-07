#!/usr/bin/env python3
"""Render the LTU walkthrough video: how to use Educational Thread with the
real programme TCTEA, shown on screenshots of the running web server.

    go run ./cmd/edthread serve -addr 127.0.0.1:8088 &
    python3 video/capture_ltu_screens.py      # screenshots -> video/out/screens/
    python3 video/make_ltu_video.py           # -> video/out/educational-thread-ltu.mp4
"""

import pathlib

from PIL import Image, ImageFont

import make_video as mv
from make_video import BAD, CARD, GOOD, INK, LINE, MUTED, ROLE, THREAD, W, S, tint

SCREENS = pathlib.Path(__file__).resolve().parent / "out" / "screens"
MENLO = "/System/Library/Fonts/Menlo.ttc"

# Browser frame on the slide (logical px) and the crop window in screenshot px.
FX, FY, FW, FH, BAR = 100, 190, 1720, 850, 40
CROP_X, CROP_W = 260, 2360
CROP_H = round(CROP_W * (FH - BAR) / FW)


class ScreenCanvas(mv.Canvas):
    """A canvas that pastes screenshots after downsampling, so they stay sharp."""

    def __init__(self):
        super().__init__()
        self.pastes = []

    def frame(self):
        img = super().frame()
        for im, xy in self.pastes:
            img.paste(im, xy)
        return img


mv.Canvas = ScreenCanvas  # build() creates canvases through the module


def mono(size):
    return ImageFont.truetype(MENLO, size * S)


def screen(c, name, top, url, focus=None):
    """Draw a browser window showing screenshot `name`, scrolled to `top` (screenshot px)."""
    c.box(FX - 2, FY - 2, FW + 4, FH + 4, fill=CARD, outline=LINE, r=14, width=2)
    c.box(FX, FY, FW, BAR, fill=tint(INK, 0.9), outline=None, r=12)
    c.box(FX, FY + BAR - 12, FW, 12, fill=tint(INK, 0.9), outline=None, r=0)
    for i, col in enumerate(("#E0605A", "#E5B84B", "#5CB860")):
        c.circle(FX + 24 + i * 22, FY + BAR / 2, 7, col)
    c.box(FX + 110, FY + 8, 760, BAR - 16, fill=CARD, outline=None, r=8)
    c.text(FX + 126, FY + BAR / 2, url, 18, "medium", MUTED, "lm")
    img = Image.open(SCREENS / f"{name}.png").convert("RGB")
    top = max(0, min(top, img.height - CROP_H))
    crop = img.crop((CROP_X, top, CROP_X + CROP_W, top + CROP_H)).resize((FW, FH - BAR), Image.LANCZOS)
    c.pastes.append((crop, (FX, FY + BAR)))


def arrow(c, x1, x2, y, col=INK):
    c.line([(x1, y), (x2 - 14, y)], col, 4)
    c.head((x2, y), (x1, y), col, 18)


def caption(c, role, text):
    x = 100
    if role:
        x += c.pill(100, 64, role.upper() if role in ROLE else role, ROLE.get(role, INK), size=22) + 20
    c.text(x, 82, text, 40, "bold", INK, "lm")


def chrome(c, scene_no, total):
    c.box(0, 1072, W * (scene_no + 1) / total, 8, fill=INK, outline=None, r=0)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def s_title(c, step):
    c.text(W / 2, 330, "Educational Thread at LTU", 96, "bold", INK, "mm")
    c.text(W / 2, 430, "A walkthrough with a real programme", 42, "medium", MUTED, "mm")
    c.text(W / 2, 510, "Civilingenjör teknisk fysik och elektroteknik (TCTEA)", 34, "demi", INK, "mm")
    mv.thread_decoration(c, 700)
    note = "Prototype · built from LTU’s public study plan and syllabi · not an LTU service"
    w = c.tw(note, 22, "medium") + 40
    c.box((W - w) / 2, 880, w, 46, fill=CARD, outline=LINE, r=23)
    c.text(W / 2, 903, note, 22, "medium", MUTED, "mm")


def doc_icon(c, x, y, w, h, title, sub, color):
    c.box(x, y, w, h, fill=CARD, outline=color, r=10, width=3)
    c.box(x + w - 40, y, 40, 40, fill=tint(color, 0.7), outline=None, r=0)
    for i in range(4):
        c.box(x + 24, y + 100 + i * 22, w - 48 - (60 if i == 3 else 0), 8, fill=tint(INK, 0.85), outline=None, r=4)
    c.text(x + 24, y + 32, title, 26, "bold", INK)
    c.text(x + 24, y + 64, sub, 20, "medium", MUTED)


def s_pipeline(c, step):
    c.text(100, 90, "Where the data comes from", 54, "bold")
    col = ROLE["teacher"]
    doc_icon(c, 100, 230, 440, 210, "Study plan", "utbildningsplan TCTEA, intake H26", col)
    doc_icon(c, 100, 470, 440, 210, "65 course syllabi", "kursplaner, Swedish and English", col)
    if step >= 1:
        arrow(c, 548, 656, 455)
        c.box(660, 395, 330, 120, fill=INK, outline=None, r=16)
        c.text(825, 438, "importer", 30, "bold", "#FFFFFF", "mm")
        c.text(825, 476, "tools/ltu/import_tctea.py", 18, "medium", tint(INK, 0.5), "mm")
        arrow(c, 998, 1096, 455)
        c.box(1100, 230, 720, 450, fill=CARD, outline=INK, r=20, width=3)
        c.text(1136, 270, "Knowledge graph", 30, "bold", INK, "lm")
        stats = [("300", "credits"), ("3", "specialisations"), ("65", "courses"), ("470", "learning outcomes")]
        for i, (n, label) in enumerate(stats):
            x, y = 1136 + (i % 2) * 340, 330 + (i // 2) * 140
            c.text(x, y + 30, n, 64, "bold", ROLE["student"], "lm")
            c.text(x, y + 90, label, 24, "demi", INK, "lm")
        c.text(1136, 640, "every item linked to the document it came from", 22, "medium", MUTED, "lm")
    if step >= 2:
        c.box(1100, 740, 720, 200, fill=tint(col, 0.88), outline=col, r=20, width=3)
        c.pill(1136, 764, "PROPOSED · DRAFT", col, size=18)
        c.text(1136, 838, "~30 outcome links along calculus, linear analysis,", 26, "demi", INK, "lm")
        c.text(1136, 876, "circuits, signals, modelling and control", 26, "demi", INK, "lm")
        c.text(1136, 916, "kept apart, for the teachers to review", 22, "medium", MUTED, "lm")
        c.line([(1460, 740), (1460, 680)], col, 4, dash=(10, 8))
        c.head((1460, 682), (1460, 700), col, 16)


def s_start(c, step):
    if step == 0:
        c.text(100, 90, "Getting started", 54, "bold")
        c.box(260, 260, 1400, 420, fill="#1B1F27", outline=None, r=20)
        for i, col in enumerate(("#E0605A", "#E5B84B", "#5CB860")):
            c.circle(300 + i * 24, 296, 8, col)
        lines = [("# 1  read LTU's study plan and syllabi", "#7F8796"),
                 ("python3 tools/ltu/import_tctea.py", "#E8E6E1"),
                 ("# 2  load everything into GraphDB (validated)", "#7F8796"),
                 ("go run ./cmd/edthread setup", "#E8E6E1"),
                 ("# 3  start the web pages", "#7F8796"),
                 ("go run ./cmd/edthread serve", "#E8E6E1")]
        for i, (t, col) in enumerate(lines):
            c.d.text((310 * S, (350 + i * 50) * S), ("$ " if not t.startswith("#") else "") + t,
                     font=mono(28), fill=col)
        return
    caption(c, None, "Pick a role and a question")
    screen(c, "home", 0, "127.0.0.1:8080/")


def s_student(c, step):
    caption(c, "student", "Where is what I learn now used later?")
    screen(c, "student", 140 if step == 0 else 1888, "127.0.0.1:8080/q/1-student-where-used")


def s_advisor(c, step):
    if step == 2:
        caption(c, "advisor", "Consent given to another university: refused")
        screen(c, "advisor-refused", 560, "127.0.0.1:8080/q/3-advisor-readiness")
        return
    caption(c, "advisor", "Is this student ready for Modelling and Control?")
    screen(c, "advisor", 130 if step == 0 else 1290, "127.0.0.1:8080/q/3-advisor-readiness")


def s_teacher(c, step):
    caption(c, "teacher", "Do my syllabus’s entry requirements fit the programme?")
    screen(c, "teacher", 130, "127.0.0.1:8080/q/9-teacher-syllabus-check")


def s_employer(c, step):
    caption(c, "employer", "What does this specialisation really cover?")
    screen(c, "employer" if step == 0 else "skills", 300,
           "127.0.0.1:8080/q/" + ("7-employer-topic-profile" if step == 0 else "8-employer-skills"))


def s_contribute(c, step):
    c.text(100, 90, "Teachers make the thread better", 54, "bold")
    c.box(160, 210, 1600, 330, fill="#1B1F27", outline=None, r=20)
    c.d.text((200 * S, 240 * S), "data/public/ltu/proposed-threads.ttl", font=mono(22), fill="#7F8796")
    code = [("# R0004E entry requirements: \"Basic knowledge about the Laplace", "#7F8796"),
            ("# transform, for example as acquired in M0018M Linear Analysis\"", "#7F8796"),
            ("lo:R0004E-4  et:requires  lo:M0018M-4 .", "#E8E6E1"),
            ("lo:R0004E-3  et:requires  lo:M0066M-7 ;  et:uses  lo:F0004T-3 .", "#E8E6E1")]
    for i, (t, col) in enumerate(code):
        c.d.text((200 * S, (300 + i * 52) * S), t, font=mono(28), fill=col)
    if step >= 1:
        steps = [("confirm, correct or add", ROLE["teacher"]), ("edthread setup", INK),
                 ("validated (SHACL)", GOOD), ("live in every page", ROLE["student"])]
        x = 160
        for i, (t, col) in enumerate(steps):
            w = 340
            c.box(x, 640, w, 120, fill=tint(col, 0.86), outline=col, r=18, width=3)
            c.para_mid(x + w / 2, 700, t, 28, "bold", INK, maxw=w - 40)
            if i < len(steps) - 1:
                arrow(c, x + w + 12, x + w + 74, 700)
            x += w + 86
        c.text(W / 2, 850, "Every link keeps its reason, and answers that rely on a draft link can be traced back to it.",
               26, "medium", MUTED, "mm")


def s_next(c, step):
    c.text(100, 90, "Next steps at LTU", 54, "bold")
    items = [("Review the proposed links", "with the programme’s teachers, then extend them", ROLE["teacher"]),
             ("Map exam modules to outcomes", "which module assesses what", ROLE["advisor"]),
             ("Swedish pages", "the Swedish texts are already in the data", ROLE["student"]),
             ("Log-in for advisors and admissions", "so the office asking for consent is known", ROLE["employer"])]
    for i, (t, sub, col) in enumerate(items):
        x, y = 100 + (i % 2) * 870, 230 + (i // 2) * 330
        c.box(x, y, 830, 280, fill=CARD, outline=LINE, r=20)
        c.box(x, y, 14, 280, fill=col, outline=None, r=0)
        c.text(x + 50, y + 70, f"{i + 1}", 60, "bold", col, "lm")
        c.para(x + 130, y + 40, t, 36, "bold", INK, maxw=650)
        c.para(x + 130, y + 150, sub, 26, "medium", MUTED, maxw=650)


def s_close(c, step):
    c.text(W / 2, 380, "Educational Thread", 110, "bold", INK, "mm")
    c.text(W / 2, 480, "One thread, from the first course to working life.", 44, "medium", MUTED, "mm")
    mv.thread_decoration(c, 720)


SCENES = [
    (s_title, ["This is a short walkthrough of Educational Thread at LTU, using a real programme: "
               "Engineering Physics and Electrical Engineering."]),
    (s_pipeline, [
        "Everything starts from LTU's own public documents: the study plan, and the sixty-five course "
        "syllabi, in Swedish and English.",
        "An importer turns them into a knowledge graph. Three hundred credits, three specialisations, and "
        "four hundred and seventy learning outcomes, each one linked to the document it came from.",
        "The syllabi do not say which outcome builds on which. Those links are drafted separately, clearly "
        "marked as a proposal, for the teachers to review.",
    ]),
    (s_start, [
        "Getting started takes three commands: import the documents, load them into GraphDB, and start the "
        "web pages.",
        "The start page offers questions by role: student, study advisor, teacher, admissions, and employer.",
    ]),
    (s_student, [
        "A student in Single Variable Calculus 2 picks the course and asks where it is used later.",
        "Differential equations come back in Linear Analysis, Circuit Theory, Modelling and Control, and "
        "Dynamic Systems. A good reason to keep going.",
    ]),
    (s_advisor, [
        "A study advisor checks whether a student is ready for Modelling and Control. The student presents "
        "their credentials, with consent for LTU's study guidance, for advising only.",
        "Every prerequisite is listed, including indirect ones. One is missing: the transforms from Linear "
        "Analysis. Exactly what the course syllabus asks for.",
        "A record whose consent was given to another university is refused. The student stays in control.",
    ]),
    (s_teacher, [
        "A teacher checks a syllabus against the programme. Linear Analysis still names three course codes "
        "that are no longer part of it. Easy to miss by hand, easy to fix once seen.",
    ]),
    (s_employer, [
        "An employer picks a specialisation, Electronic Systems and Automatic Control, and sees where the "
        "credits really go, subject by subject.",
        "And which skills it builds toward, through which courses, and for which occupations.",
    ]),
    (s_contribute, [
        "Teachers make the thread better. Each proposed link is one line, with its reason from the syllabus.",
        "Confirm it, correct it, or add your own, then reload. The data is validated before it goes live.",
    ]),
    (s_next, [
        "Next steps at LTU: review the links with the programme's teachers, map exam modules to outcomes, "
        "add Swedish pages, and a log-in for advisors and admissions.",
    ]),
    (s_close, ["Educational Thread. One thread, from the first course to working life."]),
]


if __name__ == "__main__":
    mv.build(SCENES, "educational-thread-ltu", chrome_fn=chrome)
