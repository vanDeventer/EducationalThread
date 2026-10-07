package wallet

import (
	"encoding/json"
	"os"
	"testing"
	"time"
)

const (
	advisors   = "https://data.example.edu/org/study-advisor-office"
	admissions = "https://data.example.edu/org/admissions-office"
)

func load(t *testing.T, name string) *Presentation {
	t.Helper()
	data, err := os.ReadFile("../../data/learners/" + name)
	if err != nil {
		t.Fatal(err)
	}
	p, err := Parse(data)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func day(s string) time.Time {
	d, _ := time.Parse("2006-01-02", s)
	return d
}

func TestSampleWalletsAreMinimal(t *testing.T) {
	for _, name := range []string{"student-s.json", "applicant-a.json"} {
		if probs := load(t, name).Problems(); len(probs) > 0 {
			t.Errorf("%s: %v", name, probs)
		}
	}
}

func TestConsent(t *testing.T) {
	s := load(t, "student-s.json")
	cases := []struct {
		requester, purpose, today string
		want                      bool
	}{
		{advisors, "academic advising", "2026-10-07", true},
		{advisors, "academic advising", "2027-06-30", true},  // last valid day
		{advisors, "academic advising", "2027-07-01", false}, // expired
		{advisors, "marketing", "2026-10-07", false},         // other purpose
		{admissions, "academic advising", "2026-10-07", false},
	}
	for _, c := range cases {
		if got := s.Consents(c.requester, c.purpose, day(c.today)); got != c.want {
			t.Errorf("Consents(%s, %q, %s) = %v, want %v", c.requester, c.purpose, c.today, got, c.want)
		}
	}
	if load(t, "applicant-a.json").Consents(advisors, "academic advising", day("2026-10-07")) {
		t.Error("applicant consented to advisors")
	}
}

func TestDemonstrated(t *testing.T) {
	got := load(t, "applicant-a.json").Demonstrated()
	want := []string{
		"https://data.example.org/outcome/MA101-LO1", "https://data.example.org/outcome/MA101-LO2",
		"https://data.example.org/outcome/MA201-LO1", "https://data.example.org/outcome/MA201-LO2",
	}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestProblemsDetectsIdentifyingData(t *testing.T) {
	var raw map[string]any
	data, _ := os.ReadFile("../../data/learners/applicant-a.json")
	json.Unmarshal(data, &raw)
	vc := raw["verifiableCredential"].([]any)[0].(map[string]any)
	vc["credentialSubject"].(map[string]any)["email"] = "a@example.org"
	raw["holder"] = "applicant-a"
	data, _ = json.Marshal(raw)
	p, err := Parse(data)
	if err != nil {
		t.Fatal(err)
	}
	if n := len(p.Problems()); n < 2 {
		t.Fatalf("expected holder and email problems, got %v", p.Problems())
	}
}

func TestIssuerAsString(t *testing.T) {
	p, err := Parse([]byte(`{"holder":"did:example:x","verifiableCredential":[{"id":"urn:c","issuer":"https://i.example",
		"credentialSubject":{"id":"did:example:x","achievement":{"id":"https://lo.example/1"}}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	if p.Credentials[0].Issuer.ID != "https://i.example" || len(p.Demonstrated()) != 1 {
		t.Fatalf("got %+v", p.Credentials[0])
	}
}
