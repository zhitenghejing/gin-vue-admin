package webui

import (
	"fmt"
	"io/fs"
	"net/http"
	"strings"
)

// newHandler only serves existing regular files. Hash routing needs no HTML fallback.
func newHandler(api http.Handler, assets fs.FS) (http.Handler, error) {
	index, err := fs.Stat(assets, "index.html")
	if err != nil {
		return nil, fmt.Errorf("embedded index.html is missing: %w", err)
	}
	if !index.Mode().IsRegular() || index.Size() == 0 {
		return nil, fmt.Errorf("embedded index.html must be a non-empty regular file")
	}
	files := http.FileServer(http.FS(assets))
	proxy := http.StripPrefix("/api", api)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api" || strings.HasPrefix(r.URL.Path, "/api/") {
			proxy.ServeHTTP(w, r)
			return
		}
		name := strings.TrimPrefix(r.URL.Path, "/")
		if name == "" {
			name = "index.html"
		}
		if fs.ValidPath(name) {
			info, err := fs.Stat(assets, name)
			if err == nil && info.Mode().IsRegular() {
				if r.Method != http.MethodGet && r.Method != http.MethodHead {
					w.Header().Set("Allow", "GET, HEAD")
					http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
					return
				}
				// Includes public files without hashes; never pin them across releases.
				w.Header().Set("Cache-Control", "no-cache")
				w.Header().Set("X-Content-Type-Options", "nosniff")
				files.ServeHTTP(w, r)
				return
			}
		}
		// Preserve native API routes (including /health and uploads) and their 404s.
		api.ServeHTTP(w, r)
	}), nil
}
