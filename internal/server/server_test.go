package server

import (
	"bytes"
	"context"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/vanDeventer/EducationalThread/internal/graphdb"
)

// These tests run the real queries against GraphDB. They are skipped unless
// the repository exists (run `go run ./cmd/edthread setup` first). Set
// EDTHREAD_GRAPHDB / EDTHREAD_REPO to test against another server.
func newTestServer(t *testing.T) *Server {
	t.Helper()
	base, repo := os.Getenv("EDTHREAD_GRAPHDB"), os.Getenv("EDTHREAD_REPO")
	if base == "" {
		base = "http://localhost:7200"
	}
	if repo == "" {
		repo = "edthread"
	}
	db := graphdb.New(base, repo)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if ok, err := db.RepositoryExists(ctx); err != nil || !ok {
		t.Skipf("GraphDB repository %s/%s not available (%v)", base, repo, err)
	}
	s, err := New(db, "../..")
	if err != nil {
		t.Fatal(err)
	}
	s.Now = func() time.Time { return time.Date(2026, 10, 7, 12, 0, 0, 0, time.UTC) }
	return s
}

func get(t *testing.T, s *Server, path string) (int, string) {
	t.Helper()
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec.Code, rec.Body.String()
}

func postWallet(t *testing.T, s *Server, path, wallet string, upload []byte) (int, string) {
	t.Helper()
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	mw.WriteField("wallet", wallet)
	if upload != nil {
		fw, _ := mw.CreateFormFile("walletfile", "wallet.json")
		fw.Write(upload)
	}
	mw.Close()
	req := httptest.NewRequest(http.MethodPost, path, &body)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

var rowCount = regexp.MustCompile(`(\d+) row\(s\)`)

func rows(t *testing.T, html string) string {
	t.Helper()
	m := rowCount.FindStringSubmatch(html)
	if m == nil {
		return "0"
	}
	return m[1]
}

func TestHomeListsEveryQuery(t *testing.T) {
	s := newTestServer(t)
	code, html := get(t, s, "/")
	if code != http.StatusOK {
		t.Fatalf("status %d", code)
	}
	for name := range s.byName {
		if !strings.Contains(html, "/q/"+name) {
			t.Errorf("home page does not link %s", name)
		}
	}
}

func TestPublicQueries(t *testing.T) {
	s := newTestServer(t)
	cases := map[string]string{
		"/q/1-student-where-used":      "8",
		"/q/2-student-career-link":     "5",
		"/q/4-teacher-sequence":        "6",
		"/q/5-teacher-alignment-check": "2",
		"/q/7-employer-topic-profile":  "3",
		"/q/8-employer-skills":         "4",
		"/q/9-teacher-syllabus-check":  "3",
		"/q/10-advisor-shared-courses": "18",
		"/q/12-teacher-same-outcomes":  "1",
	}
	for path, want := range cases {
		code, html := get(t, s, path)
		if code != http.StatusOK || rows(t, html) != want {
			t.Errorf("%s: status %d, %s rows, want %s", path, code, rows(t, html), want)
		}
	}
}

func TestParameterChoice(t *testing.T) {
	s := newTestServer(t)
	_, html := get(t, s, "/q/1-student-where-used?course="+url.QueryEscape("https://data.example.edu/course/M0001"))
	if !strings.Contains(html, "Ordinary Differential Equations") {
		t.Error("Calculus outcomes should be used in the ODE course")
	}
	code, _ := get(t, s, "/q/1-student-where-used?course="+url.QueryEscape("https://evil.example/x> } ?s ?p ?o {"))
	if code != http.StatusBadRequest {
		t.Errorf("unoffered parameter: status %d, want 400", code)
	}
}

func TestAdvisorNeedsConsent(t *testing.T) {
	s := newTestServer(t)
	code, html := get(t, s, "/q/3-advisor-readiness")
	if code != http.StatusOK || strings.Contains(html, "row(s)") {
		t.Fatal("wallet query must not run before credentials are presented")
	}
	code, html = postWallet(t, s, "/q/3-advisor-readiness", "student-s.json", nil)
	if code != http.StatusOK || strings.Count(html, ">NOT MET<") != 3 || rows(t, html) != "10" {
		t.Errorf("student-s: status %d, %s rows, %d not met", code, rows(t, html), strings.Count(html, ">NOT MET<"))
	}
	code, _ = postWallet(t, s, "/q/3-advisor-readiness", "applicant-a.json", nil)
	if code != http.StatusForbidden {
		t.Errorf("applicant-a consented only to admissions: status %d, want 403", code)
	}
	code, _ = postWallet(t, s, "/q/3-advisor-readiness", "../../go.mod", nil)
	if code != http.StatusBadRequest {
		t.Errorf("path traversal: status %d, want 400", code)
	}
}

func TestAdmissionGap(t *testing.T) {
	s := newTestServer(t)
	code, html := postWallet(t, s, "/q/6-admission-gap", "applicant-a.json", nil)
	if code != http.StatusOK || rows(t, html) != "3" {
		t.Fatalf("status %d, %s rows", code, rows(t, html))
	}
	for _, unit := range []string{"First-order ODEs", "Laplace transform", "Systems of linear ODEs"} {
		if !strings.Contains(html, unit) {
			t.Errorf("missing bridging unit %s", unit)
		}
	}
}

func TestUploadedWalletWithNameIsRefused(t *testing.T) {
	s := newTestServer(t)
	data, err := os.ReadFile("../../data/learners/applicant-a.json")
	if err != nil {
		t.Fatal(err)
	}
	named := bytes.Replace(data, []byte(`"type": [
          "AchievementSubject"
        ],`), []byte(`"type": ["AchievementSubject"], "name": "Alice Applicant",`), 1)
	if bytes.Equal(named, data) {
		t.Fatal("test fixture did not change")
	}
	code, html := postWallet(t, s, "/q/6-admission-gap", "upload", named)
	if code != http.StatusUnprocessableEntity || !strings.Contains(html, "identifying data") {
		t.Errorf("status %d", code)
	}
}

func TestExpertSPARQL(t *testing.T) {
	s := newTestServer(t)
	post := func(q string) (int, string) {
		req := httptest.NewRequest(http.MethodPost, "/sparql", strings.NewReader(url.Values{"query": {q}}.Encode()))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		rec := httptest.NewRecorder()
		s.ServeHTTP(rec, req)
		b, _ := io.ReadAll(rec.Body)
		return rec.Code, string(b)
	}
	if code, html := post(exampleSPARQL); code != http.StatusOK || rows(t, html) == "0" {
		t.Errorf("example query: status %d", code)
	}
	if code, _ := post("SELECT * WHERE { SERVICE <http://localhost:7200/repositories/uedm> { ?s ?p ?o } }"); code != http.StatusBadRequest {
		t.Errorf("SERVICE: status %d, want 400", code)
	}
	if code, _ := post("INSERT DATA { <urn:a> <urn:b> <urn:c> }"); code != http.StatusBadRequest {
		t.Errorf("update: status %d, want 400", code)
	}
}

// --- The real programme (LTU TCTEA), imported from public syllabi -------------

const ltu = "https://w3id.org/edthread/ltu/"

func TestRealProgrammeAdvisor(t *testing.T) {
	s := newTestServer(t)
	post := func(walletName, target string) (int, string) {
		var body bytes.Buffer
		mw := multipart.NewWriter(&body)
		mw.WriteField("wallet", walletName)
		mw.WriteField("target", target)
		mw.Close()
		req := httptest.NewRequest(http.MethodPost, "/q/3-advisor-readiness", &body)
		req.Header.Set("Content-Type", mw.FormDataContentType())
		rec := httptest.NewRecorder()
		s.ServeHTTP(rec, req)
		return rec.Code, rec.Body.String()
	}
	code, html := post("ltu-student-k.json", ltu+"course/R0004E")
	if code != http.StatusOK || !strings.Contains(html, "Study and career guidance, LTU") {
		t.Fatalf("status %d; consent should be checked against LTU's study advising", code)
	}
	// Student K has passed the year-1 courses but not Linear Analysis (Laplace transform).
	if strings.Count(html, ">NOT MET<") != 1 || !strings.Contains(html, "Linear Analysis") {
		t.Errorf("want exactly the Linear Analysis transform outcome missing; got %d not met", strings.Count(html, ">NOT MET<"))
	}
	// Student S consented to Example Tech's advisors, not LTU's.
	if code, _ := post("student-s.json", ltu+"course/R0004E"); code != http.StatusForbidden {
		t.Errorf("consent given to another university: status %d, want 403", code)
	}
}

func TestRealProgrammeStudentThread(t *testing.T) {
	s := newTestServer(t)
	_, html := get(t, s, "/q/1-student-where-used?course="+url.QueryEscape(ltu+"course/M0066M"))
	for _, later := range []string{"Linear Analysis", "Circuit Theory", "Modelling and Control"} {
		if !strings.Contains(html, later) {
			t.Errorf("differential equations in M0066M should lead to %s", later)
		}
	}
}

func TestRealProgrammeEmployer(t *testing.T) {
	s := newTestServer(t)
	path := "/q/7-employer-topic-profile?pathway=" + url.QueryEscape(ltu+"program-TCTEA-electronic-systems-control")
	code, html := get(t, s, path)
	if code != http.StatusOK || !strings.Contains(html, "Automatic Control") || !strings.Contains(html, "Physics") {
		t.Errorf("status %d; subject profile incomplete", code)
	}
}

func TestRealProgrammeSyllabusCheck(t *testing.T) {
	s := newTestServer(t)
	_, html := get(t, s, "/q/9-teacher-syllabus-check?course="+url.QueryEscape(ltu+"course/R0004E"))
	if !strings.Contains(html, "S0004E") {
		t.Error("R0004E's entry requirements name S0004E, which is not in the programme")
	}
}

func TestTwoProgrammesShareCourses(t *testing.T) {
	s := newTestServer(t)
	// R0004E names S0004E Signals and Systems in its entry requirements: not part of
	// TCTEA, but a course in TCDAA, so it is now known by name rather than "retired code?".
	_, html := get(t, s, "/q/9-teacher-syllabus-check?course="+url.QueryEscape(ltu+"course/R0004E"))
	if !strings.Contains(html, "S0004E Signals and systems") {
		t.Error("S0004E should be resolved through the TCDAA programme")
	}
	_, html = get(t, s, "/q/7-employer-topic-profile?pathway="+url.QueryEscape(ltu+"program-TCDAA-industrial-computer-systems"))
	if !strings.Contains(html, "Computer Engineering") {
		t.Error("TCDAA specialisation profile should include Computer Engineering")
	}
}

func TestProgrammeSwitch(t *testing.T) {
	s := newTestServer(t)
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	mw.WriteField("wallet", "ltu-student-third-year.json")
	mw.WriteField("pathway", ltu+"program-TCDAA-industrial-computer-systems")
	mw.Close()
	req := httptest.NewRequest(http.MethodPost, "/q/11-advisor-programme-switch", &body)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, req)
	html := rec.Body.String()
	// Consent is to LTU's study advising, found through the specialisation's programme.
	if rec.Code != http.StatusOK || !strings.Contains(html, "Study and career guidance, LTU") {
		t.Fatalf("status %d", rec.Code)
	}
	// A TCTEA student halfway through year 3: 7 TCDAA courses passed, Signals and
	// systems covered through the proposed equivalence with Signal analysis, 15 to take.
	if got := strings.Count(html, ">passed<"); got != 7 {
		t.Errorf("passed = %d, want 7", got)
	}
	if !strings.Contains(html, "covered by equivalent outcomes</span></td><td>S0004E") {
		t.Error("S0004E should be covered by equivalent outcomes")
	}
	if got := strings.Count(html, "<td>to take</td>"); got != 15 {
		t.Errorf("to take = %d, want 15", got)
	}
}
