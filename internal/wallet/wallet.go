// Package wallet reads a learner's verifiable presentation (Open Badges 3.0
// credentials plus a holder policy in termsOfUse), checks the holder's consent
// and extracts the demonstrated learning outcomes.
//
// Signatures are NOT verified in this example. A production verifier must
// check each credential's proof and the issuer's trust before using it.
package wallet

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
)

// Presentation is the subset of a W3C Verifiable Presentation used here.
type Presentation struct {
	Holder      string       `json:"holder"`
	TermsOfUse  []Policy     `json:"termsOfUse"`
	Credentials []Credential `json:"verifiableCredential"`
}

// Policy is a holder policy expressed with ODRL terms.
type Policy struct {
	Type       string       `json:"type"`
	ID         string       `json:"id"`
	Permission []Permission `json:"permission"`
}

// Permission grants an assignee an action, under constraints.
type Permission struct {
	Assigner   string       `json:"assigner"`
	Assignee   string       `json:"assignee"`
	Action     []string     `json:"action"`
	Constraint []Constraint `json:"constraint"`
}

// Constraint is an ODRL constraint such as purpose eq "academic advising".
type Constraint struct {
	LeftOperand  string `json:"leftOperand"`
	Operator     string `json:"operator"`
	RightOperand string `json:"rightOperand"`
}

// Credential is the subset of an Open Badges 3.0 credential used here.
type Credential struct {
	ID      string  `json:"id"`
	Issuer  Issuer  `json:"issuer"`
	Subject Subject `json:"credentialSubject"`
}

// Issuer may be given as an IRI string or as a profile object.
type Issuer struct {
	ID   string
	Name string
}

func (i *Issuer) UnmarshalJSON(b []byte) error {
	if len(b) > 0 && b[0] == '"' {
		return json.Unmarshal(b, &i.ID)
	}
	var obj struct{ ID, Name string }
	if err := json.Unmarshal(b, &obj); err != nil {
		return err
	}
	i.ID, i.Name = obj.ID, obj.Name
	return nil
}

// Subject is the credential subject; Fields keeps every key for minimisation checks.
type Subject struct {
	ID          string
	Achievement struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	Fields []string
}

func (s *Subject) UnmarshalJSON(b []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	for k := range raw {
		s.Fields = append(s.Fields, k)
	}
	sort.Strings(s.Fields)
	if v, ok := raw["id"]; ok {
		if err := json.Unmarshal(v, &s.ID); err != nil {
			return fmt.Errorf("credentialSubject.id: %w", err)
		}
	}
	if v, ok := raw["achievement"]; ok {
		if err := json.Unmarshal(v, &s.Achievement); err != nil {
			return fmt.Errorf("credentialSubject.achievement: %w", err)
		}
	}
	return nil
}

// forbidden are subject attributes that would identify the learner.
var forbidden = map[string]bool{
	"name": true, "email": true, "birthDate": true, "identifier": true, "address": true, "phone": true,
}

// Parse decodes a presentation.
func Parse(data []byte) (*Presentation, error) {
	var p Presentation
	if err := json.Unmarshal(data, &p); err != nil {
		return nil, fmt.Errorf("not a valid presentation: %w", err)
	}
	if p.Holder == "" {
		return nil, fmt.Errorf("presentation has no holder")
	}
	return &p, nil
}

// Problems lists violations of the data-minimisation rules: the holder must be
// a pseudonymous DID and credential subjects must carry no identifying data.
func (p *Presentation) Problems() []string {
	var out []string
	if !strings.HasPrefix(p.Holder, "did:") {
		out = append(out, "holder must be a pseudonymous DID")
	}
	for _, c := range p.Credentials {
		for _, f := range c.Subject.Fields {
			if forbidden[f] {
				out = append(out, fmt.Sprintf("%s: credentialSubject.%s is not allowed", c.ID, f))
			}
		}
		if c.Subject.ID != p.Holder {
			out = append(out, fmt.Sprintf("%s: subject is not the holder", c.ID))
		}
		if c.Subject.Achievement.ID == "" {
			out = append(out, fmt.Sprintf("%s: no achievement id", c.ID))
		}
	}
	return out
}

// Consents reports whether the holder permits requester to read the
// presentation for purpose on the given day.
func (p *Presentation) Consents(requester, purpose string, today time.Time) bool {
	day := today.Format("2006-01-02")
	for _, pol := range p.TermsOfUse {
		for _, perm := range pol.Permission {
			if perm.Assigner != p.Holder || perm.Assignee != requester || !contains(perm.Action, "read") {
				continue
			}
			purposeOK, expired := false, false
			for _, c := range perm.Constraint {
				switch {
				case c.LeftOperand == "purpose" && c.Operator == "eq":
					purposeOK = purposeOK || c.RightOperand == purpose
				case c.LeftOperand == "dateTime" && c.Operator == "lteq":
					expired = expired || c.RightOperand < day
				}
			}
			if purposeOK && !expired {
				return true
			}
		}
	}
	return false
}

// Demonstrated returns the learning-outcome IRIs the holder has credentials for.
func (p *Presentation) Demonstrated() []string {
	seen := map[string]bool{}
	var out []string
	for _, c := range p.Credentials {
		id := c.Subject.Achievement.ID
		if c.Subject.ID == p.Holder && id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	sort.Strings(out)
	return out
}

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}
