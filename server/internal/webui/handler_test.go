package webui

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/gin-gonic/gin"
)

func TestHandler(t *testing.T) {
	api := gin.New()
	api.GET("/health", func(c *gin.Context) { c.String(http.StatusOK, "healthy") })
	api.GET("/uploads/file/a.txt", func(c *gin.Context) { c.String(http.StatusOK, "upload") })
	api.GET("/apix", func(c *gin.Context) { c.String(http.StatusOK, "native") })
	api.POST("/private", func(c *gin.Context) {
		if c.GetHeader("X-Token") != "valid" {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		body, _ := io.ReadAll(c.Request.Body)
		c.Header("New-Token", "renewed")
		c.String(http.StatusOK, "%s:%s", c.Query("q"), body)
	})
	handler, err := newHandler(api, fstest.MapFS{
		"index.html":     {Data: []byte("<html>embedded UI</html>")},
		"assets/app.js":  {Data: []byte("console.log('ui')")},
		"favicon.ico":    {Data: []byte("icon")},
		"logo.png":       {Data: []byte("logo")},
		"assets/.hidden": {Data: []byte("hidden")},
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, tt := range []struct {
		name, method, path, token, body string
		status                          int
		want                            string
	}{
		{"index", "GET", "/", "", "", 200, "<html>embedded UI</html>"},
		{"head", "HEAD", "/", "", "", 200, ""},
		{"script", "GET", "/assets/app.js", "", "", 200, "console.log('ui')"},
		{"public icon", "GET", "/favicon.ico", "", "", 200, "icon"},
		{"public logo", "GET", "/logo.png", "", "", 200, "logo"},
		{"static method", "POST", "/", "", "", 405, "method not allowed\n"},
		{"index redirect", "GET", "/index.html", "", "", 301, ""},
		{"health proxy", "GET", "/api/health", "", "", 200, "healthy"},
		{"native health", "GET", "/health", "", "", 200, "healthy"},
		{"file proxy", "GET", "/api/uploads/file/a.txt", "", "", 200, "upload"},
		{"native file", "GET", "/uploads/file/a.txt", "", "", 200, "upload"},
		{"prefix boundary", "GET", "/apix", "", "", 200, "native"},
		{"auth", "POST", "/api/private?q=value", "valid", "payload", 200, "value:payload"},
		{"unauthorized", "POST", "/api/private", "", "", 401, ""},
		{"missing api", "GET", "/api/missing", "", "", 404, "404 page not found"},
		{"missing script", "GET", "/assets/missing.js", "", "", 404, "404 page not found"},
		{"no listing", "GET", "/assets/", "", "", 404, "404 page not found"},
		{"no history fallback", "GET", "/login", "", "", 404, "404 page not found"},
		{"api priority", "GET", "/api/assets/app.js", "", "", 404, "404 page not found"},
		{"traversal", "GET", "/assets/../index.html", "", "", 404, "404 page not found"},
	} {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.path, strings.NewReader(tt.body))
			req.Header.Set("X-Token", tt.token)
			res := httptest.NewRecorder()
			handler.ServeHTTP(res, req)
			if res.Code != tt.status || res.Body.String() != tt.want {
				t.Fatalf("got %d %q, want %d %q", res.Code, res.Body.String(), tt.status, tt.want)
			}
			if tt.name == "auth" && res.Header().Get("New-Token") != "renewed" {
				t.Fatal("proxy lost response header")
			}
			if tt.name == "index" && res.Header().Get("Cache-Control") != "no-cache" {
				t.Fatal("entry HTML must not be pinned in cache")
			}
			if tt.name == "script" && !strings.Contains(res.Header().Get("Content-Type"), "javascript") {
				t.Fatalf("incorrect script MIME: %q", res.Header().Get("Content-Type"))
			}
		})
	}
}

func TestMissingIndex(t *testing.T) {
	for _, assets := range []fstest.MapFS{{}, {"index.html": {Data: nil}}} {
		if _, err := newHandler(http.NotFoundHandler(), assets); err == nil {
			t.Fatal("expected an error for missing or empty index")
		}
	}
}
