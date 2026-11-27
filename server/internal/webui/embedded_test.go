//go:build embedweb

package webui

import (
	"bytes"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"testing"
)

// Exercise the actual build output, not a placeholder dist committed to the repo.
func TestEmbeddedRelease(t *testing.T) {
	handler, err := Wrap(http.NotFoundHandler(), "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Wrap(http.NotFoundHandler(), "/api"); err == nil {
		t.Fatal("non-empty router prefix must fail rather than silently break API URLs")
	}
	count := 0
	err = fs.WalkDir(content, "dist", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		url := path[len("dist"):]
		if url == "/index.html" {
			url = "/"
		}
		res := httptest.NewRecorder()
		handler.ServeHTTP(res, httptest.NewRequest("GET", url, nil))
		want, err := content.ReadFile(path)
		if err != nil {
			return err
		}
		if res.Code != http.StatusOK || !bytes.Equal(res.Body.Bytes(), want) {
			t.Errorf("%s: status=%d, response does not match embedded file", url, res.Code)
		}
		count++
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if count < 2 {
		t.Fatal("expected index and frontend assets in release")
	}
	t.Logf("verified %d embedded files", count)
}
