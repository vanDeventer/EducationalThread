# EducationalThread
Making use of Semantic Web technology to understand and follow education as a web of digital threads.

Every course has **learning outcomes**, as stated in its syllabus. A teacher may also break a course into **learning units** (a topic with outcomes, activities and assessments). The outcomes are linked across courses, programs, institutions and occupations, and this single graph answers different questions for different people:

| Role | Question | Query |
|---|---|---|
| Student | Where will what I struggle with now be used later? | [1](queries/1-student-where-used.rq) |
| Student | Which occupations does this course lead to? | [2](queries/2-student-career-link.rq) |
| Study advisor | Is this student ready for the next course? | [3](queries/3-advisor-readiness.rq) *(consent)* |
| Teacher | What does my course cover, in what order, and how is it assessed? | [4](queries/4-teacher-sequence.rq) |
| Teacher | Are there sequencing or constructive-alignment problems? | [5](queries/5-teacher-alignment-check.rq) |
| Teacher | Do my syllabus's entry requirements fit the programme? | [9](queries/9-teacher-syllabus-check.rq) |
| Study advisor | Which courses carry over between two programmes? | [10](queries/10-advisor-shared-courses.rq) |
| Study advisor | What would switching programme mean for this student? | [11](queries/11-advisor-programme-switch.rq) *(consent)* |
| Teacher | Which other courses state the same outcomes as mine? | [12](queries/12-teacher-same-outcomes.rq) |
| Admissions | Which units is this applicant missing to join year 2? | [6](queries/6-admission-gap.rq) *(consent)* |
| Employer | What does this degree with a flashy name actually cover? | [7](queries/7-employer-topic-profile.rq), [8](queries/8-employer-skills.rq) |

The repository holds two datasets that the same queries run on:
- **Two real programmes** at Luleå University of Technology, imported from LTU's public study plans and course syllabi: *Civilingenjör teknisk fysik och elektroteknik* (TCTEA) and *Civilingenjör datateknik* (TCDAA). Each is 300 credits with three specialisations; together they have 103 distinct courses (18 in both programmes) and 715 syllabus outcomes. See [Real programmes](#real-programmes-ltu-tctea-and-tcdaa).
- **A small fictitious example** (Example Institute of Technology, Other University) that has what syllabi lack: learning units, course instances, Bloom levels and a teacher's week plan.

## Running it

### Web server on GraphDB

Requires Go 1.22+ and a running [GraphDB](https://graphdb.ontotext.com) (the free edition is enough).

```sh
go run ./cmd/edthread setup            # create repository "edthread" and load the data (-recreate to start over)
go run ./cmd/edthread serve            # http://127.0.0.1:8080
go test ./...                          # server tests run against GraphDB; skipped if the repository is absent
```

Flags: `-graphdb http://localhost:7200` (or `EDTHREAD_GRAPHDB`), `-repo edthread` (or `EDTHREAD_REPO`), `-addr`, `-root`. `edthread check` re-runs the integrity checks.

The server offers:
- **One page per question.** Choices (course, program, specialisation, course instance) come from the graph.
- **Consent pages.** The advisor and admissions pages ask the learner to present credentials. You can use the sample presentations or upload one.
- **An expert SPARQL page.** It runs read-only queries against the public graph, with federated `SERVICE` calls disabled.

### Offline, without GraphDB

Requires Python 3.9+ with `rdflib` and `pyshacl` (`pip install -r requirements.txt`).

```sh
python3 run.py all         # validation, integrity checks, wallet checks, then every query
python3 run.py query 6     # one query
```

Both runners execute the same files in `queries/`, so their answers must agree.

### Videos

Needs macOS (for the `say` voice) and `pip install -r video/requirements.txt`; output goes to `video/out/`.

```sh
python3 video/make_video.py                 # introduction to the idea
go run ./cmd/edthread serve -addr 127.0.0.1:8088 &
python3 video/capture_ltu_screens.py        # screenshots of the running server (headless Chrome)
python3 video/make_ltu_video.py             # walkthrough with the LTU programme
```

## Layout

```
ontology/edthread.ttl          thin application profile (classes, relations, Bloom levels)
shapes/edthread-shapes.ttl     SHACL publishing contract, enforced by GraphDB on every write
shapes/edthread-advisories.ttl SHACL warnings with curriculum-design advice (checked by run.py)
shapes/checks/*.rq             graph-wide integrity checks GraphDB's SHACL cannot express (cycles, ...)
data/public/                   the curriculum graph (no personal data)
  vocab/                       topics (MSC2020-based), main subjects (ämnen), skills and occupations (ESCO placeholders)
  ltu/                         LTU programmes: generated institution.ttl, courses.ttl (shared by both
                               programmes), tctea-program.ttl and tcdaa-program.ttl, plus the
                               hand-written proposed-threads.ttl (draft outcome links)
  example-tech/                Example Institute of Technology: program, 5 courses, course instances,
                               recognition mapping of another university's outcomes
  other-university/            a second institution publishing its courses with the same profile
tools/ltu/import_ltu.py        importer: LTU study plans + syllabi (PDF) -> Turtle, with provenance
data/learners/*.json           sample learner wallets: Verifiable Presentations of Open Badges 3.0
                               credentials with an ODRL-style holder policy (consent)
queries/*.rq                   one SPARQL query per role question, with parameter headers
graphdb/manifest.json          GraphDB repository settings and which files go into which named graph
cmd/edthread/                  Go command: setup, check, serve
internal/                      graphdb client, loader, query templates, wallet/consent, web server
run.py                         offline runner (rdflib + pySHACL)
video/                         narrated videos: make_video.py (introduction), make_ltu_video.py
                               (LTU walkthrough, on screenshots from capture_ltu_screens.py)
```

## The model

```
Program ──hasSpecialisation──▶ Specialisation
   │ includesCourse                    ▲ inSpecialisation (optional: none = common core)
   ▼                                   │
ProgramCourse (year, period, mandatory/elective) ──course──▶ Course (syllabus: credits, subject, entry requirements)
                                                               │ hasOutcome        │ hasUnit (optional)
                                                               │                   ▼
                                                               │            LearningUnit ──about──▶ Topic (SKOS)
                                                               ▼                   │ hasOutcome
          Assessment ──assesses──▶ LearningOutcome ◀───────────────────────────────┘
                                    │   ▲      └──alignedToSkill──▶ Skill ◀──needsSkill── Occupation
                       requires / uses / revisits  (sub-properties of buildsOn)
                                    │
                    skos:exactMatch / closeMatch  ◀── recognition of other institutions' outcomes

Program ──educationalCredentialAwarded──▶ Qualification (EQF level)
CourseInstance (term, teacher) ──hasDelivery──▶ UnitDelivery (week) ──deliversUnit──▶ LearningUnit
Learner wallet:  credential ──achievement──▶ LearningOutcome      (holder = pseudonymous DID)
```

Design choices:
- **Outcomes belong to the course; units are optional.** Syllabi state outcomes per course (`Course et:hasOutcome`); a teacher may break a course into learning units that carry outcomes themselves. Queries follow `et:hasUnit?/et:hasOutcome`, so they work either way.
- **Outcomes, not units, carry the thread.** Units differ between institutions; outcomes can be aligned (`skos:exactMatch` / `skos:closeMatch`).
- **Three kinds of dependency.** `requires` is a hard prerequisite, used by admissions and advising. `uses` shows a student where their effort pays off. `revisits` means a later outcome deepens an earlier one. All three are sub-properties of `buildsOn`, which GraphDB infers (RDFS-Plus ruleset); `run.py` applies the same rule.
- **Programmes have specialisations.** Each placement of a course (`et:ProgramCourse`) records year, study period, mandatory or elective, and optionally its specialisation; placements without one form the common core. Employer views work on a *pathway*: a programme, or a specialisation plus its core.
- **Course vs course instance.** The syllabus (kursplan) is stable. The instance (kurstillfälle) records term, teacher and the order in which units are actually delivered.
- **Reuse before invention.** Classes are subclasses of schema.org types or are mapped with `skos:closeMatch` to the Europass Learning Model (ELM v3) and ESCO. `requires` is the inverse of CASE `isPrerequisiteOf`.

## Real programmes: LTU TCTEA and TCDAA

`python3 tools/ltu/import_ltu.py` (needs `pip install -r tools/ltu/requirements.txt`):
1. downloads the study plans of the programmes listed in its `PROGRAMS` table (intake autumn 2026), and every course syllabus in Swedish and English, caching the extracted text in `.cache/ltu/`;
2. writes `data/public/ltu/courses.ttl` with every course once, so a course in both programmes (Calculus, Physics 1, Modelling and Control, ...) is one resource that both programmes point to, and one `<code>-program.ttl` per programme.

Re-run it when LTU revises a syllabus. To add another LTU programme, add its code, page and English names to `PROGRAMS`.

**Taken from LTU's documents (factual):**
- each programme: core courses, specialisations, elective groups, free-elective credits, and each course's planned year and study period (two TCDAA electives that the study plan lists but does not schedule are included without a year);
- per course: English and Swedish name, credits, cycle, main subject, decision date, and the entry-requirement text plus the course codes it names;
- learning outcomes, verbatim, with the Higher Education Ordinance category where the syllabus gives one;
- examination modules with credits.

Every course links to its syllabus page (`schema:url`) and the exact PDFs it came from (`prov:wasDerivedFrom`). The IRIs are minted in this project's namespace; they are not LTU identifiers.

**Proposed (interpretation, needs review):** the syllabi say which *courses* a course requires, but not which *outcome* builds on which. [`proposed-threads.ttl`](data/public/ltu/proposed-threads.ttl) holds a draft of about 30 outcome links, one proposed course equivalence, and skill alignments along the calculus → linear analysis → circuits / signals → modelling and control → automatic control thread. It was drafted with AI assistance from the syllabus texts, with the reason for each link in a comment. It is its own named graph, marked as a draft with provenance, so teachers can confirm, correct or reject it, and every answer that depends on it can be traced back.

**What the real data already shows:**
- *Student:* the differential-equations outcome of Single Variable Calculus 2 (M0066M) is required by Linear Analysis, Circuit Theory, Modelling and Control, and Dynamic Systems.
- *Advisor:* the sample LTU student ([`ltu-student-k.json`](data/learners/ltu-student-k.json), consent given to LTU's study advising) is ready for Modelling and Control (R0004E) except for one outcome: the transforms of Linear Analysis (M0018M). That matches R0004E's own entry requirement, "basic knowledge about the Laplace transform, for example as acquired in M0018M".
- *Teacher:* several entry requirements still name **retired course codes**. Linear Analysis names M0047M, M0048M and M0049M; Circuit Theory names M0049M. Modelling and Control names S0004E Signals and systems, which is not in TCTEA but is a TCDAA course; with both programmes loaded, the syllabus check shows it by name instead of as a possibly retired code.
- *Advisor:* the two programmes share 18 courses but schedule several of them differently. For example, Calculus 1 is in year 1 period 1 in TCTEA but period 3 in TCDAA, while Introduction to Programming comes first in TCDAA. That matters to a student who switches programme. For one such student, the sample [`ltu-student-third-year.json`](data/learners/ltu-student-third-year.json) (TCTEA, halfway through year 3), the switch question shows that 7 mandatory TCDAA courses (52.5 credits) carry over, 1 is covered by equivalent outcomes, and 15 (120 credits) remain before year 4.
- *Teacher:* Signal analysis (S0001E, TCTEA) and Signals and systems (S0004E, TCDAA) state the same five outcomes word for word; the "same outcomes" question finds such pairs. The draft graph proposes them as equivalent (`skos:closeMatch`), which is why the switch question shows Signals and systems as covered rather than to take, labelled as such. Identical wording is a hint, not a decision: the degree projects of different specialisations share template outcomes too.
- *Employer:* credits per main subject for each specialisation's mandatory courses.

**Known limits:**
- *Outcome parsing.* Outcomes are split from PDF text by heuristics, because syllabi format them differently (bullets, numbered lists, prose). For 25 of the 103 courses the English and Swedish lists differ in length, so only the English texts are kept (the importer reports which).
- *Assessment links.* Only single-module courses link their exam to all outcomes. Other syllabi do not say which module assesses which outcome, so the advisories flag those outcomes.
- *Bloom levels.* No Bloom levels are recorded.
- *Translations.* The English names of the programmes and specialisations are our translations.
- *Proposed links.* The draft outcome links cover the control thread shared by both programmes, not yet TCDAA's computing courses.

## GraphDB setup

`edthread setup` creates the repository with:
- the `rdfsplus-optimized` ruleset
- SHACL validation on
- a context index

It then loads each named graph from [graphdb/manifest.json](graphdb/manifest.json), loading the shapes first:

| Named graph | Content |
|---|---|
| `https://w3id.org/edthread` | the ontology |
| `https://w3id.org/edthread/graph/vocab` | topics, main subjects, skills, occupations |
| `https://data.example.edu/graph/curriculum` | Example Institute of Technology |
| `https://data.example.org/graph/curriculum` | Other University |
| `https://data.example.edu/graph/recognition/other-university` | how Example Tech recognises Other University's outcomes |
| `https://w3id.org/edthread/ltu/graph/courses` | LTU programmes TCTEA and TCDAA and their syllabi (generated) |
| `https://w3id.org/edthread/ltu/graph/proposed-threads` | proposed outcome links for TCTEA (draft) |

One graph per publisher keeps provenance explicit, and lets each publisher replace its own graph.

**Validation is split in three:**

| Where | What | When |
|---|---|---|
| GraphDB SHACL | the publishing contract (`edthread-shapes.ttl`) | every write; any violation rejects the whole graph |
| `shapes/checks/*.rq` | prerequisite cycles, units delivered by the wrong course | after `setup`, and in `run.py validate` |
| `edthread-advisories.ttl` | warnings such as "no assessment linked to this outcome" | `run.py validate`, and the teacher's check page |

The warnings stay out of GraphDB because its SHACL engine treats a warning as a rejection. It also does not evaluate SPARQL-based constraints, which is why the graph-wide checks are separate queries.

## Privacy

- **The public graph never points to a person.** Personal data points *into* the public graph: a credential's achievement is a public outcome IRI.
- **Learner data is never stored.** Wallets stay with the learner; GraphDB holds only the public curriculum. When a query needs a learner's record, the server:
  1. reads the presented credentials
  2. checks the holder policy (who may read, for what purpose, until when). The reader is the office serving that function (study advising, admissions) at the university that offers the chosen course or programme, so a learner's consent to one university does not open their record to another
  3. checks data minimisation: the holder is a DID, and there are no names, e-mail addresses, IDs or birth dates
  4. passes **only the demonstrated outcome IRIs** into the query's `VALUES ?demonstrated { }` slot

  The learner's identifier never reaches the database.
- **Injection-safe parameters.** The server accepts only parameter values it offered itself, and only well-formed IRIs.
- **Credentials are not verified yet.** The sample credentials are unsigned, and the server does not verify signatures. Before real use, add proof verification and an issuer trust list.
- **Statistics (not yet modelled)** should be computed inside the institution and published only as aggregates. Use small-cell suppression and preferably differential privacy.

## What the example data is designed to show

Fictitious example:
- Student S passed Calculus, Linear Algebra and half of the ODE course. The advisor sees that Laplace, systems and stability are missing before Control Engineering. The applicant's wallet is refused on the advisor page, because the applicant consented only to admissions.
- Applicant A comes from Other University. Their outcomes are credited through the recognition mapping. Admissions sees three ODE units, 125 h in total, to bridge.
- In autumn 2026 the ODE teacher moved *Stability* before *Systems of linear ODEs*, and the teacher's check flags it. The modelling outcome is practised but never assessed, although Control and Fluid Mechanics rely on it.

## Placeholders and next steps

- **Placeholder IRIs to replace.** Replace `sk:` and `occ:` with real ESCO IRIs. Link `tp:` concepts to MSC2020 / Wikidata with `skos:exactMatch`. Replace the `w3id.org/edthread` namespace with a registered one.
- **ELM mappings.** The ELM class mappings are `skos:closeMatch`. Check them against the current ELM release before strengthening them.
- **Credential verification.** Verify credential proofs and issuer trust in `internal/wallet`.
- **Authentication.** Requester identity is currently implied by the page. Tie it to a login so the server knows which office is asking.
- **Review the proposed links.** Have TCTEA teachers review [`proposed-threads.ttl`](data/public/ltu/proposed-threads.ttl), extend it to the whole programme, and add Bloom levels and module-to-outcome mappings.
- **Bilingual pages.** Swedish labels are already in the data; the queries currently select English.
- **Aggregate statistics.** Add aggregate statistics with suppression or differential privacy.
