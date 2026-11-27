package preview

import "net/http"

// WithBuildID lets the preview manager verify the process behind its local port.
// Ordinary runs without an ID retain their existing HTTP behavior.
func WithBuildID(next http.Handler, id string) http.Handler {
	if id == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-GVA-Preview-Build", id)
		next.ServeHTTP(w, r)
	})
}
