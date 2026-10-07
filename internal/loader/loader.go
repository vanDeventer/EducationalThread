// Package loader sets up the GraphDB repository from graphdb/manifest.json:
// it creates the repository, loads each named graph in order (shapes first,
// so GraphDB validates the data as it arrives) and runs the integrity checks
// in shapes/checks/*.rq that GraphDB's SHACL engine cannot evaluate.
package loader

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/vanDeventer/EducationalThread/internal/graphdb"
)

// Manifest describes the repository and which files go into which named graph.
type Manifest struct {
	Repository struct {
		Title  string            `json:"title"`
		Params map[string]string `json:"params"`
	} `json:"repository"`
	Graphs []struct {
		Graph string   `json:"graph"`
		Files []string `json:"files"`
	} `json:"graphs"`
}

// ReadManifest reads graphdb/manifest.json below root.
func ReadManifest(root string) (*Manifest, error) {
	data, err := os.ReadFile(filepath.Join(root, "graphdb", "manifest.json"))
	if err != nil {
		return nil, err
	}
	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("graphdb/manifest.json: %w", err)
	}
	return &m, nil
}

// Setup creates the repository if needed (or recreates it) and loads all graphs.
func Setup(ctx context.Context, c *graphdb.Client, root string, recreate bool, log io.Writer) error {
	m, err := ReadManifest(root)
	if err != nil {
		return err
	}
	exists, err := c.RepositoryExists(ctx)
	if err != nil {
		return err
	}
	if exists && recreate {
		fmt.Fprintf(log, "deleting repository %s\n", c.Repo)
		if err := c.DeleteRepository(ctx); err != nil {
			return err
		}
		exists = false
	}
	if !exists {
		fmt.Fprintf(log, "creating repository %s\n", c.Repo)
		if err := c.CreateRepository(ctx, m.Repository.Title, m.Repository.Params); err != nil {
			return err
		}
	}
	for _, g := range m.Graphs {
		var buf strings.Builder
		for _, f := range g.Files {
			data, err := os.ReadFile(filepath.Join(root, f))
			if err != nil {
				return err
			}
			buf.Write(data)
			buf.WriteString("\n")
		}
		if err := c.PutGraph(ctx, g.Graph, []byte(buf.String())); err != nil {
			return err
		}
		fmt.Fprintf(log, "loaded %-62s %d file(s)\n", g.Graph, len(g.Files))
	}
	violations, err := Check(ctx, c, root)
	if err != nil {
		return err
	}
	if len(violations) > 0 {
		return fmt.Errorf("integrity checks failed:\n  %s", strings.Join(violations, "\n  "))
	}
	fmt.Fprintln(log, "integrity checks passed")
	return nil
}

// Check runs shapes/checks/*.rq; every row returned is a violation.
func Check(ctx context.Context, c *graphdb.Client, root string) ([]string, error) {
	files, err := filepath.Glob(filepath.Join(root, "shapes", "checks", "*.rq"))
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	var out []string
	for _, f := range files {
		q, err := os.ReadFile(f)
		if err != nil {
			return nil, err
		}
		res, err := c.Query(ctx, string(q))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", filepath.Base(f), err)
		}
		for _, row := range res.Rows {
			out = append(out, fmt.Sprintf("%s: %s: %s", filepath.Base(f), row["focus"].Value, row["message"].Value))
		}
	}
	return out, nil
}

// PublicFiles lists every Turtle file under data/public, for checking that the
// manifest is complete.
func PublicFiles(root string) ([]string, error) {
	var out []string
	err := filepath.WalkDir(filepath.Join(root, "data", "public"), func(p string, d os.DirEntry, err error) error {
		if err == nil && !d.IsDir() && strings.HasSuffix(p, ".ttl") {
			rel, _ := filepath.Rel(root, p)
			out = append(out, filepath.ToSlash(rel))
		}
		return err
	})
	sort.Strings(out)
	return out, err
}
