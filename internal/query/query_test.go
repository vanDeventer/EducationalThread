package query

import (
	"strings"
	"testing"
)

func TestLoadDirParsesRepositoryQueries(t *testing.T) {
	qs, err := LoadDir("../../queries")
	if err != nil {
		t.Fatal(err)
	}
	if len(qs) != 12 {
		t.Fatalf("got %d queries, want 12", len(qs))
	}
	byName := map[string]*Query{}
	for _, q := range qs {
		byName[q.Name] = q
	}
	adv := byName["3-advisor-readiness"]
	if adv == nil || !adv.NeedsWallet() || adv.Purpose != "academic advising" || adv.RequesterOf != "target" ||
		adv.RequesterFunction != "https://w3id.org/edthread#studyAdvising" {
		t.Fatalf("advisor query not parsed as a wallet query: %+v", adv)
	}
	if len(adv.Params) != 1 || adv.Params[0].Var != "target" || adv.Params[0].Kind != "course" ||
		adv.Params[0].Default != "https://data.example.edu/course/E0020" {
		t.Fatalf("advisor params = %+v", adv.Params)
	}
	if byName["1-student-where-used"].NeedsWallet() {
		t.Fatal("student query must not need a wallet")
	}
}

const sample = `# title: T
# role: advisor
# param: target course
# wallet: w.json
# requester-function: https://example.org/fn/advising
# requester-of: target
# purpose: advising
PREFIX c: <https://example.org/course/>
SELECT * WHERE {
  VALUES ?target { c:A }
  OPTIONAL { VALUES ?demonstrated { } FILTER (?demonstrated = ?x) }
}`

func TestBind(t *testing.T) {
	q, err := Parse("t", sample)
	if err != nil {
		t.Fatal(err)
	}
	if q.Params[0].Default != "https://example.org/course/A" {
		t.Fatalf("default = %q", q.Params[0].Default)
	}
	got, err := q.Bind(map[string]string{"target": "https://example.org/course/B"},
		[]string{"https://example.org/lo/1", "https://example.org/lo/2"})
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"VALUES ?target { <https://example.org/course/B> }",
		"VALUES ?demonstrated { <https://example.org/lo/1> <https://example.org/lo/2> }",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("bound query lacks %q:\n%s", want, got)
		}
	}
}

func TestBindKeepsDefaultsAndEmptySlot(t *testing.T) {
	q, _ := Parse("t", sample)
	got, err := q.Bind(nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(got, "VALUES ?target { c:A }") || !strings.Contains(got, "VALUES ?demonstrated {  }") {
		t.Fatalf("unexpected:\n%s", got)
	}
}

func TestBindRejectsInjection(t *testing.T) {
	q, _ := Parse("t", sample)
	for _, bad := range []string{
		"https://example.org/x> } ?s ?p ?o {",
		"not an iri",
		"https://example.org/a b",
		`https://example.org/"x"`,
	} {
		if _, err := q.Bind(map[string]string{"target": bad}, nil); err == nil {
			t.Errorf("parameter %q accepted", bad)
		}
		if _, err := q.Bind(nil, []string{bad}); err == nil {
			t.Errorf("demonstrated %q accepted", bad)
		}
	}
}

func TestParseRejectsWalletQueryWithoutSlot(t *testing.T) {
	text := strings.Replace(sample, "VALUES ?demonstrated { }", "", 1)
	if _, err := Parse("t", text); err == nil {
		t.Fatal("wallet query without slot accepted")
	}
}
