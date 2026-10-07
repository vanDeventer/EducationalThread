package loader

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/vanDeventer/EducationalThread/internal/graphdb"
)

// Every public Turtle file must be loaded into GraphDB, and only once.
func TestManifestCoversPublicData(t *testing.T) {
	root := "../.."
	m, err := ReadManifest(root)
	if err != nil {
		t.Fatal(err)
	}
	listed := map[string]int{}
	for _, g := range m.Graphs {
		for _, f := range g.Files {
			listed[f]++
			if _, err := os.Stat(filepath.Join(root, f)); err != nil {
				t.Errorf("manifest lists missing file %s", f)
			}
		}
	}
	files, err := PublicFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		if listed[f] != 1 {
			t.Errorf("%s is listed %d times in graphdb/manifest.json", f, listed[f])
		}
	}
	if m.Graphs[0].Graph != graphdb.ShapesGraph {
		t.Error("shapes must be loaded first so data is validated as it arrives")
	}
}
