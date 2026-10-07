// Command edthread sets up the Educational Thread repository in GraphDB and
// serves the role-based web pages.
//
//	edthread setup [-recreate]   create the repository and load graphdb/manifest.json
//	edthread check               run the integrity checks against GraphDB
//	edthread serve               serve the web pages (default http://127.0.0.1:8080)
//
// Common flags: -graphdb http://localhost:7200  -repo edthread  -root .
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vanDeventer/EducationalThread/internal/graphdb"
	"github.com/vanDeventer/EducationalThread/internal/loader"
	"github.com/vanDeventer/EducationalThread/internal/server"
)

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	cmd, args := os.Args[1], os.Args[2:]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	gdbURL := fs.String("graphdb", envOr("EDTHREAD_GRAPHDB", "http://localhost:7200"), "GraphDB base URL")
	repo := fs.String("repo", envOr("EDTHREAD_REPO", "edthread"), "GraphDB repository id")
	root := fs.String("root", ".", "repository root (with queries/, data/, shapes/, graphdb/)")
	recreate := fs.Bool("recreate", false, "setup: delete and recreate the repository")
	addr := fs.String("addr", "127.0.0.1:8080", "serve: listen address")
	fs.Parse(args)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db := graphdb.New(*gdbURL, *repo)

	var err error
	switch cmd {
	case "setup":
		err = loader.Setup(ctx, db, *root, *recreate, os.Stdout)
	case "check":
		var v []string
		if v, err = loader.Check(ctx, db, *root); err == nil && len(v) > 0 {
			for _, line := range v {
				fmt.Println(line)
			}
			err = errors.New("integrity checks failed")
		} else if err == nil {
			fmt.Println("integrity checks passed")
		}
	case "serve":
		err = serve(ctx, db, *root, *addr)
	default:
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "edthread:", err)
		os.Exit(1)
	}
}

func serve(ctx context.Context, db *graphdb.Client, root, addr string) error {
	ok, err := db.RepositoryExists(ctx)
	if err != nil {
		return err
	}
	if !ok {
		return fmt.Errorf("repository %q not found in GraphDB; run 'edthread setup' first", db.Repo)
	}
	h, err := server.New(db, root)
	if err != nil {
		return err
	}
	srv := &http.Server{Addr: addr, Handler: h, ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutdown)
	}()
	slog.Info("serving Educational Thread", "url", "http://"+addr, "graphdb", db.BaseURL, "repo", db.Repo)
	if err := srv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func usage() {
	fmt.Fprintln(os.Stderr, `usage: edthread <setup|check|serve> [flags]

  setup [-recreate]  create the GraphDB repository and load graphdb/manifest.json
  check              run the integrity checks in shapes/checks against GraphDB
  serve [-addr]      serve the role-based pages

flags: -graphdb URL (default http://localhost:7200, env EDTHREAD_GRAPHDB)
       -repo ID     (default edthread, env EDTHREAD_REPO)
       -root DIR    (default .)`)
	os.Exit(2)
}
