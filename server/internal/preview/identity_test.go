package preview

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestIdentityPreservesResponse(t *testing.T) {
	for _, id := range []string{"", "test-build"} {
		next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnauthorized)
			w.Write([]byte(r.URL.Path))
		})
		res := httptest.NewRecorder()
		WithBuildID(next, id).ServeHTTP(res, httptest.NewRequest("GET", "/private", nil))
		if res.Code != http.StatusUnauthorized || res.Body.String() != "/private" || res.Header().Get("X-GVA-Preview-Build") != id {
			t.Fatalf("unexpected response for build %q: %+v", id, res)
		}
	}
}
