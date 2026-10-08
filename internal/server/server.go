// Package server is the Educational Thread web front end: one page per
// role-based question, plus an expert SPARQL page, backed by GraphDB.
//
// Browsers never talk to GraphDB. The server only runs the curated queries in
// queries/*.rq, only with parameter values it offered itself, and only reads a
// learner's wallet after checking the holder's consent. From a wallet it takes
// nothing but the demonstrated outcome IRIs; the presentation is neither
// stored nor sent to GraphDB.
package server

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"html/template"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/vanDeventer/EducationalThread/internal/graphdb"
	"github.com/vanDeventer/EducationalThread/internal/query"
	"github.com/vanDeventer/EducationalThread/internal/wallet"
)

//go:embed templates/*.html static/*
var assets embed.FS

const (
	maxWalletBytes = 256 << 10
	maxRows        = 500
)

// Role describes one stakeholder group on the home page.
type Role struct {
	ID, Name, Question string
	Queries            []*query.Query
}

var roleOrder = []Role{
	{ID: "student", Name: "Student", Question: "Why am I learning this?"},
	{ID: "advisor", Name: "Study advisor", Question: "Is this student ready for the next course?"},
	{ID: "teacher", Name: "Teacher", Question: "Does my course hang together?"},
	{ID: "admissions", Name: "Admissions", Question: "What is this applicant missing?"},
	{ID: "employer", Name: "Employer", Question: "What does this degree really cover?"},
}

// optionQueries list what a parameter of each kind can be set to (English labels).
var optionQueries = map[string]string{
	"course": optionPrefixes + `
SELECT ?id ?label ?group WHERE {
  ?id a et:Course ; schema:courseCode ?code ; schema:name ?name ; schema:provider/schema:name ?group .
  FILTER (lang(?name) IN ("", "en") && lang(?group) IN ("", "en"))
  BIND (CONCAT(?code, " ", STR(?name)) AS ?label) }
ORDER BY ?group ?label`,
	"program": optionPrefixes + `
SELECT ?id ?label ?group WHERE {
  ?id a et:Program ; schema:name ?label ; schema:provider/schema:name ?group .
  FILTER (lang(?label) IN ("", "en") && lang(?group) IN ("", "en")) }
ORDER BY ?group ?label`,
	// A program without specialisations, or a specialisation of a program.
	"pathway": optionPrefixes + `
SELECT ?id ?label ?group WHERE {
  {
    ?id a et:Program ; schema:name ?label ; schema:provider/schema:name ?group .
    FILTER NOT EXISTS { ?id et:hasSpecialisation ?anySpecialisation }
    FILTER (lang(?label) IN ("", "en"))
  } UNION {
    ?program et:hasSpecialisation ?id ; schema:name ?pn ; schema:provider/schema:name ?group .
    ?id schema:name ?sn .
    FILTER (lang(?pn) IN ("", "en") && lang(?sn) IN ("", "en"))
    BIND (CONCAT(STR(?pn), " — ", STR(?sn)) AS ?label)
  }
  FILTER (lang(?group) IN ("", "en")) }
ORDER BY ?group ?label`,
	"instance": optionPrefixes + `
SELECT ?id ?label ?group WHERE {
  ?id a et:CourseInstance ; et:academicTerm ?term ; et:instanceOf ?c .
  ?c schema:name ?name ; schema:provider/schema:name ?group .
  FILTER (lang(?name) IN ("", "en") && lang(?group) IN ("", "en"))
  BIND (CONCAT(STR(?name), " — ", STR(?term)) AS ?label) }
ORDER BY ?group ?label`,
}

const optionPrefixes = "PREFIX et: <https://w3id.org/edthread#> PREFIX schema: <https://schema.org/>"

// Prefixes used to shorten IRIs in result tables.
var prefixes = []struct{ prefix, ns string }{
	{"et", "https://w3id.org/edthread#"},
	{"tp", "https://w3id.org/edthread/topic/"},
	{"sk", "https://w3id.org/edthread/skill/"},
	{"occ", "https://w3id.org/edthread/occupation/"},
	{"c", "https://data.example.edu/course/"},
	{"u", "https://data.example.edu/unit/"},
	{"lo", "https://data.example.edu/outcome/"},
	{"ci", "https://data.example.edu/course-instance/"},
	{"prog", "https://data.example.edu/program/"},
	{"org", "https://data.example.edu/org/"},
	{"oulo", "https://data.example.org/outcome/"},
	{"ltuc", "https://w3id.org/edthread/ltu/course/"},
	{"ltulo", "https://w3id.org/edthread/ltu/outcome/"},
	{"ltu", "https://w3id.org/edthread/ltu/"},
	{"ouc", "https://data.example.org/course/"},
	{"schema", "https://schema.org/"},
	{"skos", "http://www.w3.org/2004/02/skos/core#"},
	{"rdfs", "http://www.w3.org/2000/01/rdf-schema#"},
}

var federated = regexp.MustCompile(`(?i)\bSERVICE\b`)

const exampleSPARQL = `PREFIX et:     <https://w3id.org/edthread#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <https://schema.org/>

# Every pair of outcomes linked by any kind of dependency (inferred et:buildsOn).
SELECT ?laterCourse ?later ?earlier ?earlierCourse
WHERE {
  ?l et:buildsOn ?e .
  ?l rdfs:label ?later . ?e rdfs:label ?earlier .
  ?lc et:hasUnit/et:hasOutcome ?l ; schema:name ?laterCourse .
  ?ec et:hasUnit/et:hasOutcome ?e ; schema:name ?earlierCourse .
  FILTER (?lc != ?ec)
}
ORDER BY ?laterCourse ?earlierCourse
`

// Server serves the web front end.
type Server struct {
	db      *graphdb.Client
	root    string
	roles   []Role
	byName  map[string]*query.Query
	wallets []string
	pages   map[string]*template.Template
	mux     *http.ServeMux
	Now     func() time.Time // for tests
}

// New loads queries and sample wallets below root and prepares the routes.
func New(db *graphdb.Client, root string) (*Server, error) {
	qs, err := query.LoadDir(filepath.Join(root, "queries"))
	if err != nil {
		return nil, err
	}
	s := &Server{db: db, root: root, byName: map[string]*query.Query{}, Now: time.Now}
	for _, r := range roleOrder {
		for _, q := range qs {
			if q.Role == r.ID {
				r.Queries = append(r.Queries, q)
			}
		}
		s.roles = append(s.roles, r)
	}
	for _, q := range qs {
		s.byName[q.Name] = q
		for _, p := range q.Params {
			if _, ok := optionQueries[p.Kind]; !ok {
				return nil, fmt.Errorf("query %s: unknown parameter kind %q", q.Name, p.Kind)
			}
		}
	}
	files, _ := filepath.Glob(filepath.Join(root, "data", "learners", "*.json"))
	for _, f := range files {
		s.wallets = append(s.wallets, filepath.Base(f))
	}
	sort.Strings(s.wallets)

	funcs := template.FuncMap{"roleName": s.roleName, "heading": heading,
		"deref": func(b *bool) bool { return b != nil && *b }}
	s.pages = map[string]*template.Template{}
	for _, page := range []string{"home", "query", "sparql"} {
		t, err := template.New("layout.html").Funcs(funcs).ParseFS(assets, "templates/layout.html", "templates/table.html", "templates/"+page+".html")
		if err != nil {
			return nil, err
		}
		s.pages[page] = t
	}

	static, _ := fs.Sub(assets, "static")
	s.mux = http.NewServeMux()
	s.mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServerFS(static)))
	s.mux.HandleFunc("GET /{$}", s.handleHome)
	s.mux.HandleFunc("GET /q/{name}", s.handleQuery)
	s.mux.HandleFunc("POST /q/{name}", s.handleQuery)
	s.mux.HandleFunc("GET /sparql", s.handleSPARQL)
	s.mux.HandleFunc("POST /sparql", s.handleSPARQL)
	return s, nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self' data:")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	s.mux.ServeHTTP(w, r)
}

func (s *Server) roleName(id string) string {
	for _, r := range roleOrder {
		if r.ID == id {
			return r.Name
		}
	}
	return id
}

// --- Home ---------------------------------------------------------------------

func (s *Server) handleHome(w http.ResponseWriter, r *http.Request) {
	s.render(w, http.StatusOK, "home", map[string]any{"Title": "Educational Thread", "Roles": s.roles})
}

// --- Role questions -------------------------------------------------------------

// Option is one choice for a parameter.
type Option struct{ Value, Label string }

// OptGroup groups options by publisher.
type OptGroup struct {
	Label   string
	Options []Option
}

// ParamView is a parameter as shown in the form.
type ParamView struct {
	Var, Kind, Selected string
	Groups              []OptGroup
}

// Table is a rendered result.
type Table struct {
	Vars      []string
	Rows      [][]string
	Truncated bool
	Boolean   *bool
}

type queryPage struct {
	Title          string
	Query          *query.Query
	Params         []ParamView
	RequesterLabel string
	Wallets        []string
	WalletSelected string
	Ran            bool
	Consent        string // set when credentials were accepted
	Refusal        string // set when credentials were refused
	Error          string
	Results        *Table
	SPARQL         string
}

func (s *Server) handleQuery(w http.ResponseWriter, r *http.Request) {
	q, ok := s.byName[r.PathValue("name")]
	if !ok {
		http.NotFound(w, r)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 45*time.Second)
	defer cancel()
	if r.Method == http.MethodPost {
		r.Body = http.MaxBytesReader(w, r.Body, maxWalletBytes+64<<10)
		if err := r.ParseMultipartForm(maxWalletBytes); err != nil && !errors.Is(err, http.ErrNotMultipart) {
			s.render(w, http.StatusBadRequest, "query", &queryPage{Title: q.Title, Query: q, Error: "Could not read the form: " + err.Error()})
			return
		}
	}

	page := &queryPage{Title: q.Title, Query: q}
	status := http.StatusOK
	values := map[string]string{}
	for _, p := range q.Params {
		groups, err := s.options(ctx, p.Kind)
		if err != nil {
			page.Error = "GraphDB is not reachable: " + err.Error()
			s.render(w, http.StatusBadGateway, "query", page)
			return
		}
		selected := r.FormValue(p.Var)
		if selected == "" {
			selected = p.Default
		}
		if !offered(groups, selected) {
			page.Error = fmt.Sprintf("%q is not a valid choice for %s.", selected, p.Var)
			s.render(w, http.StatusBadRequest, "query", page)
			return
		}
		values[p.Var] = selected
		page.Params = append(page.Params, ParamView{Var: p.Var, Kind: p.Kind, Selected: selected, Groups: groups})
	}

	var demonstrated []string
	run := true
	if q.NeedsWallet() {
		requester, label, err := s.requester(ctx, q.RequesterFunction, values[q.RequesterOf])
		if err != nil {
			page.Error = "GraphDB is not reachable: " + err.Error()
			s.render(w, http.StatusBadGateway, "query", page)
			return
		}
		page.RequesterLabel = label
		page.Wallets = s.wallets
		page.WalletSelected = r.FormValue("wallet")
		if page.WalletSelected == "" {
			page.WalletSelected = filepath.Base(q.Wallet)
		}
		run = r.Method == http.MethodPost
		if run {
			vp, err := s.readWallet(r, page.WalletSelected)
			switch {
			case requester == "":
				page.Refusal = "The university offering this has no office for this purpose in the data, so no one can ask for consent."
				status = http.StatusUnprocessableEntity
			case err != nil:
				page.Refusal, status = err.Error(), http.StatusBadRequest
			case len(vp.Problems()) > 0:
				page.Refusal = "The presentation was refused because it carries identifying data: " +
					strings.Join(vp.Problems(), "; ")
				status = http.StatusUnprocessableEntity
			case !vp.Consents(requester, q.Purpose, s.Now()):
				page.Refusal = fmt.Sprintf("The holder has not consented to %s reading these credentials for “%s” (or the consent has expired).",
					page.RequesterLabel, q.Purpose)
				status = http.StatusForbidden
			default:
				demonstrated = vp.Demonstrated()
				page.Consent = fmt.Sprintf("Consent checked: %s may read these credentials for “%s”. %d learning outcomes disclosed; nothing else from the presentation is used or stored.",
					page.RequesterLabel, q.Purpose, len(demonstrated))
			}
			run = page.Refusal == ""
		}
	}

	if run {
		text, err := q.Bind(values, demonstrated)
		if err == nil {
			page.SPARQL = text
			var res *graphdb.Results
			res, err = s.db.Query(ctx, text)
			if err == nil {
				page.Results, page.Ran = toTable(res), true
			}
		}
		if err != nil {
			page.Error, status = err.Error(), http.StatusBadGateway
		}
	}
	s.render(w, status, "query", page)
}

func (s *Server) readWallet(r *http.Request, choice string) (*wallet.Presentation, error) {
	var data []byte
	if choice == "upload" {
		f, _, err := r.FormFile("walletfile")
		if err != nil {
			return nil, errors.New("choose a presentation file to upload")
		}
		defer f.Close()
		data, err = io.ReadAll(io.LimitReader(f, maxWalletBytes))
		if err != nil {
			return nil, err
		}
	} else {
		known := false
		for _, w := range s.wallets {
			known = known || w == choice
		}
		if !known {
			return nil, fmt.Errorf("unknown sample wallet %q", choice)
		}
		var err error
		data, err = os.ReadFile(filepath.Join(s.root, "data", "learners", choice))
		if err != nil {
			return nil, err
		}
	}
	return wallet.Parse(data)
}

func (s *Server) options(ctx context.Context, kind string) ([]OptGroup, error) {
	res, err := s.db.Query(ctx, optionQueries[kind])
	if err != nil {
		return nil, err
	}
	var groups []OptGroup
	for _, row := range res.Rows {
		g := row["group"].Value
		if len(groups) == 0 || groups[len(groups)-1].Label != g {
			groups = append(groups, OptGroup{Label: g})
		}
		last := &groups[len(groups)-1]
		last.Options = append(last.Options, Option{Value: row["id"].Value, Label: row["label"].Value})
	}
	return groups, nil
}

func offered(groups []OptGroup, value string) bool {
	for _, g := range groups {
		for _, o := range g.Options {
			if o.Value == value {
				return true
			}
		}
	}
	return false
}

// requester finds the office that serves function at the provider of the
// chosen course, program or specialisation (through its program), with its English name. Both IRIs are trusted:
// function comes from a query file and subject was checked against the options.
func (s *Server) requester(ctx context.Context, function, subject string) (iri, label string, err error) {
	if !query.ValidIRI(function) || !query.ValidIRI(subject) {
		return "", "", nil
	}
	res, err := s.db.Query(ctx, optionPrefixes+`
SELECT ?office ?name WHERE {
  <`+subject+`> (^et:hasSpecialisation)?/schema:provider ?org .
  ?office schema:parentOrganization ?org ; et:servesFunction <`+function+`> .
  OPTIONAL { ?office schema:name ?name . FILTER (lang(?name) IN ("", "en")) }
} LIMIT 1`)
	if err != nil || len(res.Rows) == 0 {
		return "", "the responsible office", err
	}
	iri, label = res.Rows[0]["office"].Value, res.Rows[0]["name"].Value
	if label == "" {
		label = compact(iri)
	}
	return iri, label, nil
}

// --- Expert SPARQL --------------------------------------------------------------

type sparqlPage struct {
	Title   string
	Text    string
	Error   string
	Results *Table
}

func (s *Server) handleSPARQL(w http.ResponseWriter, r *http.Request) {
	page := &sparqlPage{Title: "Expert SPARQL", Text: exampleSPARQL}
	if r.Method != http.MethodPost {
		s.render(w, http.StatusOK, "sparql", page)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 64<<10)
	page.Text = r.FormValue("query")
	if strings.TrimSpace(page.Text) == "" {
		page.Error = "Enter a SELECT or ASK query."
		s.render(w, http.StatusBadRequest, "sparql", page)
		return
	}
	if federated.MatchString(page.Text) {
		page.Error = "Federated queries (SERVICE) are disabled on this server."
		s.render(w, http.StatusBadRequest, "sparql", page)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 45*time.Second)
	defer cancel()
	res, err := s.db.Query(ctx, page.Text)
	if err != nil {
		page.Error = err.Error()
		s.render(w, http.StatusBadRequest, "sparql", page)
		return
	}
	page.Results = toTable(res)
	s.render(w, http.StatusOK, "sparql", page)
}

// --- Rendering ------------------------------------------------------------------

func toTable(res *graphdb.Results) *Table {
	t := &Table{Vars: res.Vars, Boolean: res.Boolean}
	for i, row := range res.Rows {
		if i == maxRows {
			t.Truncated = true
			break
		}
		cells := make([]string, len(res.Vars))
		for j, v := range res.Vars {
			term, ok := row[v]
			switch {
			case !ok:
			case term.Type == "uri":
				cells[j] = compact(term.Value)
			default:
				cells[j] = term.Value
			}
		}
		t.Rows = append(t.Rows, cells)
	}
	return t
}

// heading turns a SPARQL variable name such as "taughtIn" into "taught in".
func heading(v string) string {
	var b strings.Builder
	for i, r := range v {
		if i > 0 && r >= 'A' && r <= 'Z' {
			b.WriteByte(' ')
		}
		b.WriteRune(r)
	}
	return strings.ToLower(b.String())
}

func compact(iri string) string {
	for _, p := range prefixes {
		if strings.HasPrefix(iri, p.ns) {
			return p.prefix + ":" + strings.TrimPrefix(iri, p.ns)
		}
	}
	return iri
}

func (s *Server) render(w http.ResponseWriter, status int, page string, data any) {
	var buf strings.Builder
	if err := s.pages[page].ExecuteTemplate(&buf, "layout.html", data); err != nil {
		slog.Error("rendering page", "page", page, "err", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	io.WriteString(w, buf.String())
}
