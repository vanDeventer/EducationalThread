// Package query loads the role-based SPARQL queries in queries/*.rq and binds
// their parameters.
//
// A query file starts with header comments:
//
//	# title: Is this student ready for a course?
//	# role: advisor
//	# about: One-sentence description shown in the UI.
//	# param: target course            (variable ?target, chosen from courses)
//	# wallet: data/learners/student-s.json   (needs a learner's presentation)
//	# requester-function: https://w3id.org/edthread#studyAdvising
//	# requester-of: target       (the office serving that function at ?target's provider)
//	# purpose: academic advising
//
// Each parameter has a single-variable VALUES line in the body holding its
// default, e.g. `VALUES ?target { c:E0020 }`, so every file also runs as-is.
// Queries that need a wallet contain an empty `VALUES ?demonstrated { }` slot
// that is filled with the outcome IRIs from the consented credentials.
package query

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Param is a query parameter bound through a VALUES line.
type Param struct {
	Var     string // variable name without '?'
	Kind    string // course, program, pathway or instance: what the UI offers to choose from
	Default string // default value as an absolute IRI
}

// Query is one parsed query file.
type Query struct {
	Name              string // file name without extension, e.g. 3-advisor-readiness
	Title             string
	Role              string
	About             string
	Params            []Param
	Wallet            string // sample wallet path, set when the query needs learner credentials
	RequesterFunction string // IRI of the function (e.g. et:studyAdvising) of the requesting office
	RequesterOf       string // parameter whose provider's office makes the request
	Purpose           string // purpose the learner must have consented to
	Text              string
}

// NeedsWallet reports whether the query needs a learner's presentation.
func (q *Query) NeedsWallet() bool { return q.Wallet != "" }

var (
	headerLine = regexp.MustCompile(`(?m)^#\s*([\w-]+):\s*(.+?)\s*$`)
	prefixLine = regexp.MustCompile(`(?im)^\s*PREFIX\s+([A-Za-z][\w-]*)?:\s*<([^>]*)>`)
	slot       = regexp.MustCompile(`VALUES\s+\?demonstrated\s*\{\s*\}`)
	iriPattern = regexp.MustCompile("^[A-Za-z][A-Za-z0-9+.-]*:[^\\s<>\"{}|\\\\^`]+$")
)

// ValidIRI reports whether s is safe to place between <> in a SPARQL query.
func ValidIRI(s string) bool { return iriPattern.MatchString(s) }

func valuesLine(v string) *regexp.Regexp {
	return regexp.MustCompile(`VALUES\s+\?` + regexp.QuoteMeta(v) + `\s*\{([^}]*)\}`)
}

// LoadDir parses every *.rq file in dir, sorted by name.
func LoadDir(dir string) ([]*Query, error) {
	files, err := filepath.Glob(filepath.Join(dir, "*.rq"))
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	var out []*Query
	for _, f := range files {
		data, err := os.ReadFile(f)
		if err != nil {
			return nil, err
		}
		q, err := Parse(strings.TrimSuffix(filepath.Base(f), ".rq"), string(data))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		out = append(out, q)
	}
	return out, nil
}

// Parse parses the text of one query file.
func Parse(name, text string) (*Query, error) {
	q := &Query{Name: name, Text: text}
	prefixes := map[string]string{}
	for _, m := range prefixLine.FindAllStringSubmatch(text, -1) {
		prefixes[m[1]] = m[2]
	}
	for _, m := range headerLine.FindAllStringSubmatch(text, -1) {
		key, val := m[1], m[2]
		switch key {
		case "title":
			q.Title = val
		case "role":
			q.Role = val
		case "about":
			q.About = val
		case "wallet":
			q.Wallet = val
		case "requester-function":
			q.RequesterFunction = val
		case "requester-of":
			q.RequesterOf = val
		case "purpose":
			q.Purpose = val
		case "param":
			f := strings.Fields(val)
			if len(f) != 2 {
				return nil, fmt.Errorf("param header %q: want '<variable> <kind>'", val)
			}
			m := valuesLine(f[0]).FindStringSubmatch(text)
			if m == nil {
				return nil, fmt.Errorf("param %s has no 'VALUES ?%s { ... }' line", f[0], f[0])
			}
			def, err := expand(strings.TrimSpace(m[1]), prefixes)
			if err != nil {
				return nil, fmt.Errorf("param %s: %w", f[0], err)
			}
			q.Params = append(q.Params, Param{Var: f[0], Kind: f[1], Default: def})
		}
	}
	if q.Title == "" || q.Role == "" {
		return nil, fmt.Errorf("missing title or role header")
	}
	if q.NeedsWallet() {
		if q.RequesterFunction == "" || q.RequesterOf == "" || q.Purpose == "" {
			return nil, fmt.Errorf("wallet queries need requester-function, requester-of and purpose headers")
		}
		if q.Param(q.RequesterOf) == nil {
			return nil, fmt.Errorf("requester-of names %q, which is not a parameter", q.RequesterOf)
		}
		if !slot.MatchString(text) {
			return nil, fmt.Errorf("wallet query has no 'VALUES ?demonstrated { }' slot")
		}
	}
	return q, nil
}

// Param returns the parameter for variable v, or nil.
func (q *Query) Param(v string) *Param {
	for i := range q.Params {
		if q.Params[i].Var == v {
			return &q.Params[i]
		}
	}
	return nil
}

// Bind returns the query text with parameters and demonstrated outcomes filled
// in. values maps variable names to IRIs; missing variables keep their default.
// The caller must only pass IRIs it has checked (e.g. against the options it
// offered); Bind additionally rejects anything that is not a plain IRI.
func (q *Query) Bind(values map[string]string, demonstrated []string) (string, error) {
	text := q.Text
	for _, p := range q.Params {
		v, ok := values[p.Var]
		if !ok || v == "" {
			continue
		}
		if !ValidIRI(v) {
			return "", fmt.Errorf("parameter %s: not an IRI", p.Var)
		}
		text = valuesLine(p.Var).ReplaceAllLiteralString(text, "VALUES ?"+p.Var+" { <"+v+"> }")
	}
	if q.NeedsWallet() {
		terms := make([]string, 0, len(demonstrated))
		for _, iri := range demonstrated {
			if !ValidIRI(iri) {
				return "", fmt.Errorf("demonstrated outcome %q is not an IRI", iri)
			}
			terms = append(terms, "<"+iri+">")
		}
		text = slot.ReplaceAllLiteralString(text, "VALUES ?demonstrated { "+strings.Join(terms, " ")+" }")
	}
	return text, nil
}

func expand(term string, prefixes map[string]string) (string, error) {
	if strings.HasPrefix(term, "<") && strings.HasSuffix(term, ">") {
		return strings.Trim(term, "<>"), nil
	}
	if i := strings.Index(term, ":"); i >= 0 {
		if ns, ok := prefixes[term[:i]]; ok {
			return ns + term[i+1:], nil
		}
	}
	return "", fmt.Errorf("default %q is not an IRI or known prefixed name", term)
}
