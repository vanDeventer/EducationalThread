// Package graphdb is a small client for the parts of the GraphDB / RDF4J REST
// API that Educational Thread needs: repository management, replacing named
// graphs, and SPARQL SELECT/ASK queries.
package graphdb

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// ShapesGraph is the named graph from which GraphDB's SHACL engine reads shapes.
const ShapesGraph = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"

// Client talks to one repository of a GraphDB server.
type Client struct {
	BaseURL      string        // e.g. http://localhost:7200
	Repo         string        // repository id
	QueryTimeout time.Duration // server-side limit per query
	HTTP         *http.Client
}

// New returns a client for repository repo on the server at baseURL.
func New(baseURL, repo string) *Client {
	return &Client{
		BaseURL:      strings.TrimRight(baseURL, "/"),
		Repo:         repo,
		QueryTimeout: 20 * time.Second,
		HTTP:         &http.Client{Timeout: 60 * time.Second},
	}
}

// Term is one RDF term in a SPARQL JSON result.
type Term struct {
	Type     string `json:"type"` // uri, literal or bnode
	Value    string `json:"value"`
	Datatype string `json:"datatype,omitempty"`
	Lang     string `json:"xml:lang,omitempty"`
}

// Results is a SPARQL SELECT (or ASK) result.
type Results struct {
	Vars    []string
	Rows    []map[string]Term
	Boolean *bool // set for ASK queries
}

// RepositoryExists reports whether the repository is known to the server.
func (c *Client) RepositoryExists(ctx context.Context) (bool, error) {
	resp, err := c.do(ctx, http.MethodGet, "/rest/repositories/"+url.PathEscape(c.Repo), nil, "", "application/json")
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
		return true, nil
	case http.StatusNotFound:
		return false, nil
	}
	return false, httpError(resp)
}

// CreateRepository creates the repository from GraphDB's default configuration,
// overriding the given parameters (e.g. "ruleset": "rdfsplus-optimized").
func (c *Client) CreateRepository(ctx context.Context, title string, params map[string]string) error {
	resp, err := c.do(ctx, http.MethodGet, "/rest/repositories/default-config/graphdb", nil, "", "application/json")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return httpError(resp)
	}
	var cfg map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&cfg); err != nil {
		return fmt.Errorf("reading default repository config: %w", err)
	}
	defaults, ok := cfg["params"].(map[string]any)
	if !ok {
		return fmt.Errorf("unexpected default repository config")
	}
	for name, value := range params {
		p, ok := defaults[name].(map[string]any)
		if !ok {
			return fmt.Errorf("GraphDB has no repository parameter %q", name)
		}
		p["value"] = value
	}
	cfg["id"], cfg["title"], cfg["location"] = c.Repo, title, ""
	body, err := json.Marshal(cfg)
	if err != nil {
		return err
	}
	resp2, err := c.do(ctx, http.MethodPost, "/rest/repositories", bytes.NewReader(body), "application/json", "application/json")
	if err != nil {
		return err
	}
	defer resp2.Body.Close()
	if resp2.StatusCode/100 != 2 {
		return httpError(resp2)
	}
	return nil
}

// DeleteRepository removes the repository and all its data.
func (c *Client) DeleteRepository(ctx context.Context) error {
	resp, err := c.do(ctx, http.MethodDelete, "/rest/repositories/"+url.PathEscape(c.Repo), nil, "", "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return httpError(resp)
	}
	return nil
}

// PutGraph replaces the content of a named graph with the given Turtle.
// If SHACL validation rejects the data, the error lists the violations.
func (c *Client) PutGraph(ctx context.Context, graph string, turtle []byte) error {
	path := "/repositories/" + url.PathEscape(c.Repo) + "/rdf-graphs/service?graph=" + url.QueryEscape(graph)
	resp, err := c.do(ctx, http.MethodPut, path, bytes.NewReader(turtle), "text/turtle", "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 == 2 {
		return nil
	}
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if v := shaclViolations(body); len(v) > 0 {
		return &ValidationError{Graph: graph, Violations: v}
	}
	return fmt.Errorf("loading graph %s: %s: %s", graph, resp.Status, truncate(string(body), 500))
}

// Query runs a SPARQL SELECT or ASK query.
func (c *Client) Query(ctx context.Context, query string) (*Results, error) {
	form := url.Values{"query": {query}}
	if c.QueryTimeout > 0 {
		form.Set("timeout", strconv.Itoa(int(c.QueryTimeout.Seconds())))
	}
	resp, err := c.do(ctx, http.MethodPost, "/repositories/"+url.PathEscape(c.Repo),
		strings.NewReader(form.Encode()), "application/x-www-form-urlencoded", "application/sparql-results+json")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, httpError(resp)
	}
	var raw struct {
		Head    struct{ Vars []string } `json:"head"`
		Boolean *bool                   `json:"boolean"`
		Results struct {
			Bindings []map[string]Term `json:"bindings"`
		} `json:"results"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("decoding SPARQL results: %w", err)
	}
	return &Results{Vars: raw.Head.Vars, Rows: raw.Results.Bindings, Boolean: raw.Boolean}, nil
}

func (c *Client) do(ctx context.Context, method, path string, body io.Reader, contentType, accept string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if accept != "" {
		req.Header.Set("Accept", accept)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("GraphDB at %s: %w", c.BaseURL, err)
	}
	return resp, nil
}

// ValidationError reports SHACL violations that made GraphDB reject a graph.
type ValidationError struct {
	Graph      string
	Violations []string
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("SHACL validation rejected graph %s:\n  %s", e.Graph, strings.Join(e.Violations, "\n  "))
}

// shaclViolations extracts "focus node: problem" lines from the N-Triples
// validation report GraphDB returns when a transaction is rejected. The problem
// is the shape's message if it has one, otherwise "<path>: <constraint>".
func shaclViolations(report []byte) []string {
	const sh = "<http://www.w3.org/ns/shacl#"
	type result struct{ focus, message, path, component string }
	results := map[string]*result{}
	var order []string
	sc := bufio.NewScanner(bytes.NewReader(report))
	sc.Buffer(make([]byte, 64*1024), 1<<20)
	for sc.Scan() {
		parts := strings.SplitN(sc.Text(), " ", 3)
		if len(parts) < 3 || !strings.HasPrefix(parts[1], sh) {
			continue
		}
		obj := strings.TrimSuffix(strings.TrimSpace(parts[2]), " .")
		get := func() *result {
			r, ok := results[parts[0]]
			if !ok {
				r = &result{}
				results[parts[0]] = r
				order = append(order, parts[0])
			}
			return r
		}
		switch strings.TrimPrefix(parts[1], sh) {
		case "focusNode>":
			get().focus = strings.Trim(obj, "<>")
		case "resultMessage>":
			get().message = strings.Trim(obj, `"`)
		case "resultPath>":
			if strings.HasPrefix(obj, "<") {
				get().path = strings.Trim(obj, "<>")
			}
		case "sourceConstraintComponent>":
			c := strings.TrimSuffix(strings.Trim(obj, "<>"), "ConstraintComponent")
			get().component = c[strings.LastIndexAny(c, "#/")+1:]
		}
	}
	var out []string
	for _, id := range order {
		r := results[id]
		if r.focus == "" {
			continue
		}
		problem := r.message
		if problem == "" {
			problem = strings.Trim(r.path+": "+r.component, ": ")
		}
		if problem == "" {
			problem = "constraint violated"
		}
		out = append(out, r.focus+": "+problem)
	}
	return out
}

func httpError(resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	return fmt.Errorf("GraphDB %s %s: %s: %s", resp.Request.Method, resp.Request.URL.Path, resp.Status,
		truncate(strings.TrimSpace(string(body)), 500))
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
