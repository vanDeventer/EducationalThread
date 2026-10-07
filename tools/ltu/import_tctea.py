#!/usr/bin/env python3
"""Import LTU's programme TCTEA (Civilingenjör teknisk fysik och elektroteknik)
from its public study plan and course syllabi into Educational Thread Turtle.

    pip install -r tools/ltu/requirements.txt
    python3 tools/ltu/import_tctea.py            # uses .cache/ltu, downloads what is missing
    python3 tools/ltu/import_tctea.py --refresh  # download everything again

Writes data/public/ltu/tctea-program.ttl and data/public/ltu/courses.ttl.
Everything in those files is taken from LTU's documents (verbatim outcome
texts, credits, modules, entry requirements); each resource links to its source.
Interpretations (outcome-to-outcome links, skill alignment) are NOT produced
here: they live in the hand-written data/public/ltu/proposed-threads.ttl.

IRIs are minted in this project's namespace (https://w3id.org/edthread/ltu/);
they are not LTU identifiers. schema:url points to LTU's official pages.
"""

import argparse
import io
import logging
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "ltu"
OUT = ROOT / "data" / "public" / "ltu"
SUBJECTS = ROOT / "data" / "public" / "vocab" / "subjects.ttl"

PROGRAM = "TCTEA"
INTAKE = "H26"
STUDY_PLAN_URL = ("https://epok.ltu.se/epok/dynpdf/public/utbildningsplan/downloadPublicUtbildningsplan.pdf"
                  f"?prgKod={PROGRAM}&antagTermin={INTAKE}&continuous=true&locale=sv")
PROGRAM_PAGE = "https://www.ltu.se/utbildning/program/tctea-civilingenjor-teknisk-fysik-och-elektroteknik"
SYLLABUS_PAGE = "https://www.ltu.se/utbildning/utbildningsplan-och-kursplan/kursplan?id={code}"
UA = {"User-Agent": "EducationalThread research prototype (github.com/vanDeventer/EducationalThread)"}

NS = "https://w3id.org/edthread/ltu/"
CODE = re.compile(r"\b([A-Z]\d{4}[A-Z])\b")

# English names of the specialisations (our translation; the study plan is in Swedish).
SPECIALISATIONS = {
    "Beräkningsteknik och fysik": ("computational-engineering-physics", "Computational Engineering and Physics"),
    "Elektroniksystem och reglerteknik": ("electronic-systems-control", "Electronic Systems and Automatic Control"),
    "Fysikaliska mätmetoder och sensorsystem": ("physical-measurement-sensor-systems",
                                                "Physical Measurement Methods and Sensor Systems"),
}

OUTCOME_CATEGORIES = [
    (re.compile(r"knowledge and understanding|kunskap och förståelse", re.I), "knowledgeAndUnderstanding"),
    (re.compile(r"skills and abilit|competence and skills|färdighet och förmåga", re.I), "skillsAndAbilities"),
    (re.compile(r"judg(e)?ment|assessment and attitude|values and attitude|värderingsförmåga", re.I),
     "judgementAndApproach"),
]

MODULE_TYPES = [
    (re.compile(r"written exam|tentamen|skriftlig", re.I), "writtenExam"),
    (re.compile(r"laborat", re.I), "labWork"),
    (re.compile(r"project|projekt", re.I), "projectWork"),
    (re.compile(r"assignment|inlämning|hemuppgift|uppgift", re.I), "assignment"),
    (re.compile(r"oral|muntlig|seminar", re.I), "oralExam"),
    (re.compile(r"thesis|examensarbete|report", re.I), "report"),
]

FOOTER = re.compile(r"^(Document Education|Dokument Utbildning|Syllabus .* cr |Kursplan .* hp |Utskriftsdatum|"
                    r"=== PAGE|Utbildningsplan $|Läsåret \d{4}/\d{4}$|Civilingenjör teknisk fysik och $|"
                    r"elektroteknik$|Höst 2026 2024-|Luleå (tekniska universitet|University of Technology)|"
                    r"Telefon 0920|Phone: \+46)")


# ---------------------------------------------------------------------------
# Download and text extraction
# ---------------------------------------------------------------------------

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def pdf_text(data):
    from pypdf import PdfReader
    logging.disable(logging.WARNING)
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


def cached(path, url_fn, refresh):
    """Return (source_url, text) from the cache, downloading when needed."""
    if path.exists() and not refresh:
        first, _, rest = path.read_text().partition("\n")
        return first.removeprefix("SOURCE: "), rest
    url = url_fn()
    text = pdf_text(fetch(url))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"SOURCE: {url}\n{text}")
    time.sleep(0.5)
    return url, text


def syllabus_url(code, lang):
    page = fetch(SYLLABUS_PAGE.format(code=code)).decode("utf-8", "replace")
    m = re.search(r"downloadPublicKursplan\.pdf\?kursKod=" + code + r"&(?:amp;)?lasPeriod=(\d+)", page)
    if not m:
        raise RuntimeError(f"{code}: no syllabus PDF link on {SYLLABUS_PAGE.format(code=code)}")
    url = f"https://epok.ltu.se/epok/dynpdf/public/kursplan/downloadPublicKursplan.pdf?kursKod={code}&lasPeriod={m.group(1)}"
    return url + ("&locale=en" if lang == "en" else "")


def clean_lines(text):
    text = text.replace("\x00", "")
    return [ln.rstrip() for ln in text.splitlines() if ln.strip() and not FOOTER.match(ln.strip())]


# ---------------------------------------------------------------------------
# Study plan
# ---------------------------------------------------------------------------

def parse_study_plan(text):
    lines = clean_lines(text)
    plan = {"decision": None, "diarienummer": None, "requirements": [], "order": [], "free": {}}
    for i, ln in enumerate(lines):
        if ln == "BESLUTSDATUM":
            plan["decision"] = lines[i + 1].strip()
        if ln == "DIARIENUMMER":
            plan["diarienummer"] = lines[i + 1].strip()

    part, spec, group, year, rec = "requirements", None, None, None, None
    for ln in lines:
        s = ln.strip()
        if s == "Läsordning":
            part, spec, rec = "order", None, None
            continue
        if s.startswith("Inriktning: "):
            spec, group, rec = s.removeprefix("Inriktning: ").strip(), None, None
            continue
        if part == "requirements":
            m = re.match(r"^(.+?) (\d+(?:,\d+)?) högskolepoäng$", s)
            if m and not CODE.match(s):
                group, rec = m.group(1), None
                if group == "Valfritt utrymme":
                    plan["free"][spec] = float(m.group(2).replace(",", "."))
                continue
            m = re.match(r"^([A-Z]\d{4}[A-Z]) ", s)
            if m:
                rec = {"code": m.group(1), "spec": spec, "group": group, "text": s}
                plan["requirements"].append(rec)
            elif rec and not s.startswith(("Kurskod", "Valbart utrymme", "vilken kurser", "kurser ska", "Eller")):
                rec["text"] += " " + s
        else:
            m = re.match(r"^Årskurs (\d)", s)
            if m:
                year, rec = int(m.group(1)), None
                continue
            m = re.match(r"^(\d)(?:-(\d))? ([A-Z]\d{4}[A-Z]) ", s)
            if m:
                rec = {"code": m.group(3), "spec": spec, "year": year, "p1": int(m.group(1)),
                       "p2": int(m.group(2) or m.group(1)), "text": s}
                plan["order"].append(rec)
            elif rec and not re.match(r"^(Läsperiod|\d(-\d)? Valfritt)", s):
                rec["text"] += " " + s
    for r in plan["requirements"] + plan["order"]:
        r["elective"] = bool(re.search(r"\bValbar\b", r["text"]))
    return plan


# ---------------------------------------------------------------------------
# Syllabi
# ---------------------------------------------------------------------------

def section(lines, start, stops):
    out, on = [], False
    for ln in lines:
        s = ln.strip()
        if not on and re.match(start, s):
            on = True
            continue
        if on and any(re.match(p, s) for p in stops):
            break
        if on:
            out.append(ln)
    return out


AIM_START = {"en": r"^Course Aim$", "sv": r"^Mål/Förväntat studieresultat$"}
AIM_STOP = {"en": [r"^Contents$"], "sv": [r"^Kursinnehåll$"]}
PREAMBLE = re.compile(r"(expected to|should be able|shall be able|will be able|förväntas|ska kunna|skall kunna|"
                      r"för godkänt|for a passing grade|the students? should|studenten ska|after (the|completing|completion)|"
                      r"efter (genomgången|avslutad|väl)|be able to:?$|kunna:?$)", re.I)


def split_items(lines):
    """Split an aims section into (category, text) items."""
    items, cat, buf = [], None, []

    def flush():
        parts, listing = [], False
        for t in (t.strip() for t in buf if t.strip()):
            parts.append(("; " if listing and not parts[-1].endswith(":") else " ") + t if parts else t)
            listing = listing or (t.endswith(":") and not PREAMBLE.search(t))
        text = "".join(parts).strip(" -•;")
        text = re.sub(r"\s+", " ", text)
        if len(text) > 3:
            items.append((cat, text))
        buf.clear()

    start_marker = re.compile(r"^(•|-\s|\d+\.\d+\.?\s)")
    bullet_end = sum(ln.rstrip().endswith("•") for ln in lines)
    bullet_start = sum(bool(start_marker.match(ln.strip())) for ln in lines)
    for ln in lines:
        s = ln.strip()
        heading = re.sub(r"^\d\.?\s+", "", s)
        matched = next((c for rx, c in OUTCOME_CATEGORIES if rx.search(heading) and len(heading) < 45), None)
        if matched:
            flush()
            cat = matched
            continue
        if bullet_end >= max(1, bullet_start):
            if s == "•":
                flush()
            elif s.endswith("•"):
                buf.append(s[:-1])
                flush()
            else:
                buf.append(s)
        elif bullet_start:
            if start_marker.match(s):
                flush()
                buf.append(start_marker.sub("", s).strip())
            else:
                buf.append(s)
        else:
            buf.append(s)
    flush()
    items = strip_preambles(items)
    # Prose with a semicolon-separated list: "... be able to define ...; be familiar with ...; ..."
    if len(items) == 1 and items[0][1].count(";") >= 2:
        cat, text = items[0]
        parts = [p.strip() for p in text.split(";")]
        m = re.search(r"(able to|förväntas kunna|kunna)\s", parts[0])
        if m:
            parts[0] = parts[0][m.end():]
        items = [(cat, p[:1].upper() + p[1:]) for p in parts if len(p) > 3]
    # Inline " - " lists (all on a few lines, no bullets).
    if len(items) == 1 and items[0][1].count(" - ") >= 2:
        cat, text = items[0]
        parts = [p.strip() for p in re.split(r"\s-\s", text)]
        items = [(cat, p) for p in parts[1:] if len(p) > 3] if PREAMBLE.search(parts[0]) else \
            [(cat, p) for p in parts if len(p) > 3]
    return items


PREAMBLE_END = re.compile(r"(able to|be able|shall|should|will|kunna|ska|skall|förväntas)\s*:?$", re.I)


def strip_preambles(items):
    """Remove introductory text ("After the course, the student shall:") from outcome items."""
    out = []
    for cat, text in items:
        if ":" in text:
            head, _, rest = text.rpartition(":")
            if PREAMBLE.search(head) and PREAMBLE_END.search(head.strip()):
                text = rest.strip()
        if not text or (PREAMBLE.search(text) and PREAMBLE_END.search(text)):
            continue
        out.append((cat, text))
    return out


def parse_syllabus(code, en, sv):
    le, ls = clean_lines(en), clean_lines(sv)
    c = {"code": code}
    # Title block: "SYLLABUS", English name + credits + code (may wrap), Swedish name (may wrap).
    start = next(i for i, ln in enumerate(le) if ln.strip() == "SYLLABUS") + 1
    end = next(i for i in range(start, len(le)) if le[i].strip().endswith(code))
    title = " ".join(ln.strip() for ln in le[start:end + 1])
    m = re.match(rf"^(.+?) (\d+(?:\.\d+)?) credits {code}$", re.sub(r"\s+", " ", title))
    if not m:
        raise ValueError(f"{code}: cannot read title {title!r}")
    c["name_en"], c["credits"] = m.group(1).strip(), m.group(2)
    sv_lines = []
    for ln in le[end + 1:]:
        if ln.strip().startswith("Course syllabus admitted"):
            break
        sv_lines.append(ln.strip())
    c["name_sv"] = re.sub(r"\s+", " ", " ".join(sv_lines)).strip()
    for i, ln in enumerate(le):
        if ln.strip() == "DECISION DATE":
            c["decision"] = le[i + 1].strip()
        m = re.match(rf"^(First|Second) cycle, {code}$", ln.strip())
        if m:
            c["cycle"] = m.group(1).lower()
        m = re.match(r"^Course syllabus admitted: (.+?) -", ln.strip())
        if m:
            c["valid_from"] = m.group(1).strip()
    # Subject (ämne): common words of the English and Swedish classification lines.
    def tail(lines, level_words):
        for i, ln in enumerate(lines):
            if ln.startswith(("Education level", "Utbildningsnivå")):
                t = lines[i + 1]
                t = re.sub(r"^(" + level_words + r")\s+", "", t)
                t = re.sub(r"^([GA][12X][NFE]|GXX|AXX)\s+", "", t)
                t = re.sub(r"^((G#?|U|VG|3|4|5)\s+)+", "", t)
                return t.split()
        return []
    te, ts = tail(le, "First cycle|Second cycle"), tail(ls, "Grundnivå|Avancerad nivå")
    common = []
    for a, b in zip(te, ts):
        if a != b:
            break
        common.append(a)
    if common == te or common == ts:  # subject and SCB group have the same Swedish name
        common = ts[: len(ts) // 2] if ts[: len(ts) // 2] == ts[len(ts) // 2:] else common
    c["subject_sv"] = " ".join(common)
    c["scb_en"] = " ".join(te[len(common):])

    c["entry_en"] = re.sub(r"\s+", " ", " ".join(section(le, r"^Entry requirements$", [r"^Selection$"]))).strip()
    c["entry_sv"] = re.sub(r"\s+", " ", " ".join(section(ls, r"^Behörighet$", [r"^Urval$"]))).strip()
    c["entry_codes"] = sorted(set(CODE.findall(c["entry_en"])) - {code})

    c["outcomes_en"] = split_items(section(le, AIM_START["en"], AIM_STOP["en"]))
    c["outcomes_sv"] = split_items(section(ls, AIM_START["sv"], AIM_STOP["sv"]))

    c["modules"], rows = [], []
    for ln in section(le, r"^Modules$", [r"^Study guidance$", r"^Last revised$", r"^Syllabus established$"]):
        if re.match(r"^\d{4} ", ln.strip()):
            rows.append(ln.strip())
        elif rows and not ln.strip().startswith(("Code ", "period", "Title")):
            rows[-1] += " " + ln.strip()
    for row in rows:
        m = re.match(r"^(\d{4}) (.+?) ((?:(?:G#?|U|VG|3|4|5) ?)+) (\d+(?:\.\d+)?) (Mandatory|Optional|Elective)", row)
        if m:
            c["modules"].append({"code": m.group(1), "name": m.group(2).strip(), "grades": m.group(3).strip(),
                                 "credits": m.group(4), "status": m.group(5)})
        else:
            c.setdefault("module_problems", []).append(row)
    return c


# ---------------------------------------------------------------------------
# Turtle output
# ---------------------------------------------------------------------------

def lit(s, lang=None):
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"@{lang}' if lang else f'"{s}"'


def dec(x):
    x = str(x).replace(",", ".")
    return x if "." in x else x + ".0"


HEADER = """@prefix et:     <https://w3id.org/edthread#> .
@prefix schema: <https://schema.org/> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix subj:   <https://w3id.org/edthread/subject/> .
@prefix ltu:    <https://w3id.org/edthread/ltu/> .
@prefix c:      <https://w3id.org/edthread/ltu/course/> .
@prefix lo:     <https://w3id.org/edthread/ltu/outcome/> .
@prefix mod:    <https://w3id.org/edthread/ltu/module/> .
"""


def subject_iris():
    """Map Swedish subject names to concept IRIs from the hand-written vocabulary."""
    text = SUBJECTS.read_text()
    out = {}
    for m in re.finditer(r'subj:([\w-]+) a skos:Concept.*?skos:prefLabel [^;]*?"([^"]+)"@sv', text, re.S):
        out[m.group(2)] = "subj:" + m.group(1)
    return out


def write_courses(courses, warn):
    subjects = subject_iris()
    out = [f"# GENERATED by tools/ltu/import_tctea.py from LTU's public course syllabi — do not edit.\n"
           f"# Outcome texts are verbatim from the syllabi; each course links to its source document.\n",
           HEADER]
    for c in courses:
        code = c["code"]
        subj = subjects.get(c["subject_sv"])
        if not subj:
            warn(f"{code}: subject '{c['subject_sv']}' not in {SUBJECTS.name}")
        en, sv = c["outcomes_en"], c["outcomes_sv"]
        paired = len(en) == len(sv)
        if not paired:
            warn(f"{code}: {len(en)} English vs {len(sv)} Swedish outcomes; Swedish texts omitted")
        if not en:
            warn(f"{code}: no outcomes parsed")
        o = [f"\n# --- {code} {c['name_en']} ---\n",
             f"c:{code} a et:Course ;",
             f"    schema:courseCode {lit(code)} ;",
             f"    schema:name {lit(c['name_en'], 'en')}, {lit(c['name_sv'], 'sv')} ;",
             f"    et:credits {dec(c['credits'])} ;",
             f"    schema:provider ltu:org-ltu ;",
             f"    et:cycle et:{'firstCycle' if c.get('cycle') == 'first' else 'secondCycle'} ;"]
        if subj:
            o.append(f"    et:subject {subj} ;")
        if c["entry_en"]:
            o.append(f"    schema:coursePrerequisites {lit(c['entry_en'], 'en')}, {lit(c['entry_sv'], 'sv')} ;")
        if c["entry_codes"]:
            o.append("    et:entryRequirementNames " + ", ".join(f"c:{x}" for x in c["entry_codes"]) + " ;")
        if en:
            o.append("    et:hasOutcome " + ", ".join(f"lo:{code}-{i + 1}" for i in range(len(en))) + " ;")
        if c["modules"]:
            o.append("    et:hasAssessment " + ", ".join(f"mod:{code}-{m['code']}" for m in c["modules"]) + " ;")
        o.append(f"    schema:url <{SYLLABUS_PAGE.format(code=code)}> ;")
        o.append(f"    et:syllabusDecisionDate \"{c['decision']}\"^^xsd:date ;")
        o.append(f"    prov:wasDerivedFrom <{c['source_en']}>, <{c['source_sv']}> .")
        for i, (cat, text) in enumerate(en):
            labels = [lit(text, "en")] + ([lit(sv[i][1], "sv")] if paired else [])
            o.append(f"\nlo:{code}-{i + 1} a et:LearningOutcome ;\n    rdfs:label {', '.join(labels)}"
                     + (f" ;\n    et:outcomeCategory et:{cat} ." if cat else " ."))
        single = len(c["modules"]) == 1 and float(c["modules"][0]["credits"]) == float(c["credits"])
        for row in c.get("module_problems", []):
            warn(f"{code}: cannot read module row {row!r}")
        for m in c["modules"]:
            mtype = next((t for rx, t in MODULE_TYPES if rx.search(m["name"])), "otherAssessment")
            o.append(f"\nmod:{code}-{m['code']} a et:Assessment ;\n"
                     f"    rdfs:label {lit(m['name'], 'en')} ;\n"
                     f"    et:assessmentType et:{mtype} ;\n"
                     f"    et:moduleCode {lit(m['code'])} ;\n"
                     f"    et:credits {dec(m['credits'])} ;\n"
                     f"    et:gradeScale {lit(m['grades'])}"
                     + (" ;\n    et:assesses " + ", ".join(f"lo:{code}-{i + 1}" for i in range(len(en))) + " ."
                        if single and en else " ."))
        out.append("\n".join(o) + "\n")
    (OUT / "courses.ttl").write_text("\n".join(out))


def write_program(plan, courses_by_code, warn):
    o = ["# GENERATED by tools/ltu/import_tctea.py from LTU's public study plan — do not edit.\n", HEADER,
         "@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .\n",
         """ltu:org-ltu a schema:CollegeOrUniversity ;
    schema:name "Luleå University of Technology"@en, "Luleå tekniska universitet"@sv ;
    schema:url <https://www.ltu.se> .

# Offices that may ask learners for consent (descriptive; not LTU identifiers).
ltu:org-ltu-study-advising a schema:Organization ;
    schema:name "Study and career guidance, LTU"@en, "Studie- och karriärvägledning, LTU"@sv ;
    schema:parentOrganization ltu:org-ltu ;
    et:servesFunction et:studyAdvising .

ltu:org-ltu-admissions a schema:Organization ;
    schema:name "Admissions, LTU"@en, "Antagning, LTU"@sv ;
    schema:parentOrganization ltu:org-ltu ;
    et:servesFunction et:admissionsFunction .
""",
         f"""ltu:program-{PROGRAM} a et:Program ;
    schema:name "MSc in Engineering, Engineering Physics and Electrical Engineering"@en,
                "Civilingenjör teknisk fysik och elektroteknik"@sv ;
    schema:programPrerequisites "Grundläggande behörighet + Fysik 2, Kemi 1, Matematik 4 eller Matematik E."@sv ;
    schema:provider ltu:org-ltu ;
    schema:url <{PROGRAM_PAGE}> ;
    et:studyPlanDecisionDate "{plan['decision']}"^^xsd:date ;
    schema:identifier "{plan['diarienummer']}" ;
    prov:wasDerivedFrom <{STUDY_PLAN_URL}> ;
    schema:educationalCredentialAwarded ltu:qualification-{PROGRAM} ;
    et:hasSpecialisation {", ".join(f"ltu:program-{PROGRAM}-{s[0]}" for s in SPECIALISATIONS.values())} .

ltu:qualification-{PROGRAM} a et:Qualification ;
    schema:name "Degree of Master of Science in Engineering, Engineering Physics and Electrical Engineering"@en,
                "Civilingenjörsexamen, teknisk fysik och elektroteknik"@sv ;
    et:eqfLevel 7 .
"""]
    for sv_name, (slug, en_name) in SPECIALISATIONS.items():
        free = plan["free"].get(sv_name)
        o.append(f"ltu:program-{PROGRAM}-{slug} a et:Specialisation ;\n"
                 f"    schema:name {lit(en_name, 'en')}, {lit(sv_name, 'sv')}"
                 + (f" ;\n    et:freeElectiveCredits {dec(free)} ." if free else " ."))

    groups = {(r["spec"], r["code"]): r for r in plan["requirements"]}
    o.append(f"\n# Placements from the study plan's reading order (Läsordning), intake {INTAKE}.")
    o.append(f"ltu:program-{PROGRAM} et:includesCourse")
    placements = []
    for r in plan["order"]:
        if r["code"] not in courses_by_code:
            warn(f"study plan lists {r['code']} but no syllabus was parsed")
            continue
        req = groups.get((r["spec"], r["code"])) or groups.get((None, r["code"]))
        if not req:
            warn(f"{r['code']} is in the reading order but not in the course lists")
        p = [f"et:course c:{r['code']}", f"et:studyYear {r['year']}", f"et:studyPeriod {r['p1']}"]
        if r["p2"] != r["p1"]:
            p.append(f"et:studyPeriodEnd {r['p2']}")
        if r["spec"]:
            p.append(f"et:inSpecialisation ltu:program-{PROGRAM}-{SPECIALISATIONS[r['spec']][0]}")
        p.append("et:status et:" + ("elective" if r["elective"] or (req and req["elective"]) else "mandatory"))
        if req and req["group"]:
            p.append(f"et:courseGroup {lit(req['group'], 'sv')}")
        placements.append("    [ a et:ProgramCourse ; " + " ; ".join(p) + " ]")
    o.append(" ,\n".join(placements) + " .")
    # Core courses must appear in the reading order somewhere.
    ordered = {r["code"] for r in plan["order"]}
    for r in plan["requirements"]:
        if r["code"] not in ordered:
            warn(f"{r['code']} ({r['group']}, {r['spec'] or 'core'}) has no placement in the reading order")
    (OUT / "tctea-program.ttl").write_text("\n".join(o) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", action="store_true", help="download all documents again")
    args = ap.parse_args()
    warnings = []
    warn = warnings.append

    _, plan_text = cached(CACHE / f"{PROGRAM}-{INTAKE}.sv.txt", lambda: STUDY_PLAN_URL, args.refresh)
    plan = parse_study_plan(plan_text)
    codes = sorted({r["code"] for r in plan["requirements"] + plan["order"]})
    courses = []
    for code in codes:
        src_en, en = cached(CACHE / "syllabi" / f"{code}.en.txt", lambda: syllabus_url(code, "en"), args.refresh)
        src_sv, sv = cached(CACHE / "syllabi" / f"{code}.sv.txt", lambda: syllabus_url(code, "sv"), args.refresh)
        c = parse_syllabus(code, en, sv)
        c["source_en"], c["source_sv"] = src_en, src_sv
        courses.append(c)
    OUT.mkdir(parents=True, exist_ok=True)
    write_courses(courses, warn)
    write_program(plan, {c["code"]: c for c in courses}, warn)

    n_out = sum(len(c["outcomes_en"]) for c in courses)
    print(f"{len(courses)} courses, {n_out} outcomes, {len(plan['order'])} placements -> {OUT.relative_to(ROOT)}")
    for w in warnings:
        print("warning:", w, file=sys.stderr)


if __name__ == "__main__":
    main()
