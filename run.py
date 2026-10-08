#!/usr/bin/env python3
"""Validate the Educational Thread example and run the role-based queries offline.

    python3 run.py validate          # SHACL shapes, integrity checks and wallet checks
    python3 run.py list              # list the queries
    python3 run.py query 3           # run one query (by number or file name)
    python3 run.py all               # validate, then run every query

This is the offline twin of the Go server (cmd/edthread), which runs the same
queries against GraphDB. Only the public curriculum graph is ever loaded. For a
query that declares a wallet, the learner's presentation is read, its consent
policy is checked against the declared requester and purpose, and only the
demonstrated outcome IRIs are injected into the query's
`VALUES ?demonstrated { }` slot. The learner's identity never enters the query.
"""

import datetime
import json
import pathlib
import re
import sys
import textwrap

from pyshacl import validate
from rdflib import RDFS, Graph, URIRef

ROOT = pathlib.Path(__file__).resolve().parent
ONTOLOGY = ROOT / "ontology"
PUBLIC = ROOT / "data" / "public"
LEARNERS = ROOT / "data" / "learners"
SHAPES = ROOT / "shapes"
CHECKS = ROOT / "shapes" / "checks"
QUERIES = ROOT / "queries"

MAX_COL = 46

PREFIXES = {
    "et": "https://w3id.org/edthread#",
    "c": "https://data.example.edu/course/",
    "u": "https://data.example.edu/unit/",
    "lo": "https://data.example.edu/outcome/",
    "oulo": "https://data.example.org/outcome/",
    "ltuc": "https://w3id.org/edthread/ltu/course/",
    "ltulo": "https://w3id.org/edthread/ltu/outcome/",
}

FORBIDDEN_SUBJECT_FIELDS = {"name", "email", "birthDate", "identifier", "address", "phone"}
IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+$")
DEMONSTRATED_SLOT = re.compile(r"VALUES\s+\?demonstrated\s*\{\s*\}")


def load(*paths):
    g = Graph()
    for p in paths:
        for f in sorted(p.rglob("*.ttl")) if p.is_dir() else [p]:
            g.parse(f, format="turtle")
    for prefix, ns in PREFIXES.items():
        g.bind(prefix, ns)
    return g


def infer_subproperties(g):
    """The one RDFS rule the queries rely on (GraphDB's RDFS-Plus does this for us)."""
    supers = {}
    for p, q in g.subject_objects(RDFS.subPropertyOf):
        supers.setdefault(p, set()).add(q)
    for p, qs in supers.items():
        for s, o in list(g.subject_objects(p)):
            for q in qs:
                g.add((s, q, o))
    return g


def public_graph():
    return infer_subproperties(load(ONTOLOGY, PUBLIC))


# ---------------------------------------------------------------------------
# Wallets (verifiable presentations)
# ---------------------------------------------------------------------------

def read_wallet(path):
    return json.loads(path.read_text())


def wallet_problems(vp):
    """Data-minimisation rules for a presentation; returns a list of problems."""
    problems = []
    holder = vp.get("holder", "")
    if not holder.startswith("did:"):
        problems.append("holder must be a pseudonymous DID")
    for vc in vp.get("verifiableCredential", []):
        subject = vc.get("credentialSubject", {})
        for field in FORBIDDEN_SUBJECT_FIELDS & subject.keys():
            problems.append(f"{vc.get('id')}: credentialSubject.{field} is not allowed")
        if subject.get("id") != holder:
            problems.append(f"{vc.get('id')}: subject is not the holder")
        if not IRI.match(subject.get("achievement", {}).get("id", "")):
            problems.append(f"{vc.get('id')}: achievement id is not an IRI")
    return problems


def consented(vp, requester, purpose, today=None):
    today = (today or datetime.date.today()).isoformat()
    holder = vp.get("holder")
    for policy in vp.get("termsOfUse", []):
        for perm in policy.get("permission", []):
            if perm.get("assigner") != holder or perm.get("assignee") != requester:
                continue
            if "read" not in perm.get("action", []):
                continue
            cons = perm.get("constraint", [])
            purpose_ok = any(c.get("leftOperand") == "purpose" and c.get("operator") == "eq"
                             and c.get("rightOperand") == purpose for c in cons)
            expired = any(c.get("leftOperand") == "dateTime" and c.get("operator") == "lteq"
                          and str(c.get("rightOperand")) < today for c in cons)
            if purpose_ok and not expired:
                return True
    return False


def demonstrated(vp):
    return sorted({vc["credentialSubject"]["achievement"]["id"]
                   for vc in vp.get("verifiableCredential", [])
                   if vc.get("credentialSubject", {}).get("id") == vp.get("holder")})


def inject_demonstrated(query, iris):
    for iri in iris:
        if not IRI.match(iri):
            raise ValueError(f"not an IRI: {iri!r}")
    values = " ".join(f"<{iri}>" for iri in iris)
    return DEMONSTRATED_SLOT.sub(f"VALUES ?demonstrated {{ {values} }}", query)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_validate():
    data = public_graph()
    shapes = load(SHAPES)
    conforms, results, _ = validate(data, shacl_graph=shapes, allow_warnings=True)
    print(f"SHACL: {'conforms' if conforms else 'DOES NOT CONFORM'} ({len(data)} triples)")
    sh = "http://www.w3.org/ns/shacl#"
    grouped = {}
    for r in results.subjects(URIRef(sh + "focusNode"), None):
        severity = str(results.value(r, URIRef(sh + "resultSeverity"))).rsplit("#", 1)[1]
        message = str(results.value(r, URIRef(sh + "resultMessage")) or
                      results.value(r, URIRef(sh + "sourceConstraintComponent")))
        grouped.setdefault((severity, message), []).append(fmt(data, results.value(r, URIRef(sh + "focusNode"))))
    for (severity, message), foci in sorted(grouped.items()):
        foci = sorted(foci)
        shown = foci if severity == "Violation" else foci[:5]
        more = f" … and {len(foci) - len(shown)} more" if len(foci) > len(shown) else ""
        print(f"  {severity} ({len(foci)}): {message}\n    {', '.join(shown)}{more}")

    ok = conforms
    for check in sorted(CHECKS.glob("*.rq")):
        rows = list(data.query(check.read_text()))
        print(f"check {check.stem}: {'ok' if not rows else f'{len(rows)} violation(s)'}")
        for r in rows:
            print(f"  {r.focus}: {r.message}")
        ok = ok and not rows

    for wallet in sorted(LEARNERS.glob("*.json")):
        problems = wallet_problems(read_wallet(wallet))
        print(f"wallet {wallet.name}: {'ok' if not problems else 'PROBLEMS'}")
        for p in problems:
            print(f"  {p}")
        ok = ok and not problems
    return ok


def query_files():
    return sorted(QUERIES.glob("*.rq"))


def find_query(name):
    for q in query_files():
        if q.name == name or q.stem == name or q.name.startswith(f"{name}-"):
            return q
    sys.exit(f"no query matching '{name}'")


def header(text):
    return dict(re.findall(r"^#\s*([\w-]+):\s*(.+?)\s*$", text, re.M))


def resolve_requester(g, text, h):
    """The office serving h['requester-function'] at the provider of the parameter h['requester-of']."""
    var = h["requester-of"]
    m = re.search(r"VALUES\s+\?" + re.escape(var) + r"\s*\{([^}]*)\}", text)
    prefixes = "\n".join(re.findall(r"(?im)^\s*PREFIX\s.*$", text))
    q = f"""{prefixes}
SELECT ?office WHERE {{
  VALUES ?x {{ {m.group(1).strip()} }}
  ?x (^<https://w3id.org/edthread#hasSpecialisation>)?/<https://schema.org/provider> ?org .
  ?office <https://schema.org/parentOrganization> ?org ;
          <https://w3id.org/edthread#servesFunction> <{h['requester-function']}> .
}} LIMIT 1"""
    rows = list(g.query(q))
    return str(rows[0].office) if rows else None


def fmt(g, value):
    if value is None:
        return ""
    try:
        return g.namespace_manager.normalizeUri(value) if value.__class__.__name__ == "URIRef" else str(value)
    except Exception:
        return str(value)


def print_table(g, result):
    cols = [str(v) for v in result.vars]
    rows = [[fmt(g, r[v]) for v in result.vars] for r in result]
    if not rows:
        print("  (no results)")
        return
    widths = [min(MAX_COL, max(len(c), *(len(r[i]) for r in rows))) for i, c in enumerate(cols)]
    line = "  +" + "+".join("-" * (w + 2) for w in widths) + "+"

    def emit(cells):
        wrapped = [textwrap.wrap(c, w) or [""] for c, w in zip(cells, widths)]
        for i in range(max(len(w) for w in wrapped)):
            print("  | " + " | ".join(
                (w[i] if i < len(w) else "").ljust(width) for w, width in zip(wrapped, widths)) + " |")

    print(line)
    emit(cols)
    print(line)
    for r in rows:
        emit(r)
    print(line)


def cmd_query(path, g=None):
    text = path.read_text()
    h = header(text)
    print(f"\n== {h.get('title', path.stem)}")
    print(f"   [{path.name}] role: {h.get('role', '?')}")
    g = g if g is not None else public_graph()

    if "wallet" in h:
        requester = resolve_requester(g, text, h)
        if requester is None:
            print(f"   REFUSED: no office for {h['requester-function']} at the provider of ?{h['requester-of']}.")
            return
        vp = read_wallet(ROOT / h["wallet"])
        if not consented(vp, requester, h["purpose"]):
            print(f"   REFUSED: {h['wallet']} grants no consent to {requester} for '{h['purpose']}'.")
            return
        iris = demonstrated(vp)
        print(f"   consent: {h['wallet']} -> {requester} for '{h['purpose']}' "
              f"({len(iris)} outcomes disclosed)")
        text = inject_demonstrated(text, iris)

    print_table(g, g.query(text))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "all"
    if cmd == "validate":
        return 0 if cmd_validate() else 1
    if cmd == "list":
        for q in query_files():
            print(f"{q.name:32} {header(q.read_text()).get('title', '')}")
        return 0
    if cmd == "query" and len(argv) > 2:
        cmd_query(find_query(argv[2]))
        return 0
    if cmd == "all":
        ok = cmd_validate()
        g = public_graph()
        for q in query_files():
            cmd_query(q, g)
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
