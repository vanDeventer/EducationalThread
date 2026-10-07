package graphdb

import (
	"reflect"
	"testing"
)

// Excerpt of the N-Triples report GraphDB returns when SHACL rejects a write.
const report = `_:r1 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationResult> .
_:r1 <http://www.w3.org/ns/shacl#focusNode> <https://data.example.edu/course/X1> .
_:r1 <http://www.w3.org/ns/shacl#resultMessage> "A learning unit belongs to exactly one course." .
_:r2 <http://www.w3.org/ns/shacl#focusNode> <https://data.example.edu/outcome/LO9> .
_:r2 <http://www.w3.org/ns/shacl#resultPath> <http://www.w3.org/2000/01/rdf-schema#label> .
_:r2 <http://www.w3.org/ns/shacl#sourceConstraintComponent> <http://www.w3.org/ns/shacl#MinCountConstraintComponent> .
_:r3 <http://www.w3.org/ns/shacl#focusNode> <https://data.example.edu/outcome/LO10> .
_:s1 <http://www.w3.org/ns/shacl#message> "shape messages are not results" .
`

func TestShaclViolations(t *testing.T) {
	got := shaclViolations([]byte(report))
	want := []string{
		"https://data.example.edu/course/X1: A learning unit belongs to exactly one course.",
		"https://data.example.edu/outcome/LO9: http://www.w3.org/2000/01/rdf-schema#label: MinCount",
		"https://data.example.edu/outcome/LO10: constraint violated",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %q\nwant %q", got, want)
	}
}
