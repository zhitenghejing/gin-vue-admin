//go:build !embedweb

package webui

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDevelopmentKeepsAPIPaths(t *testing.T) {
	api := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(r.URL.Path))
	})
	handler, err := Wrap(api, "/custom")
	if err != nil {
		t.Fatal(err)
	}
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, httptest.NewRequest("GET", "/api/health", nil))
	if res.Body.String() != "/api/health" {
		t.Fatal("development mode must preserve the existing router")
	}
}
