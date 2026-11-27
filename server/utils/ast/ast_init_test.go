package ast

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"text/template"

	"github.com/flipped-aurora/gin-vue-admin/server/global"
)

// Each legacy injection/rollback test gets writable fixtures, never the checkout.
// These tests change process globals and therefore run sequentially.
func setupASTFixture(t *testing.T) {
	t.Helper()
	_, source, _, _ := runtime.Caller(0)
	server := filepath.Clean(filepath.Join(filepath.Dir(source), "../.."))
	root := t.TempDir()
	old := global.GVA_CONFIG.AutoCode
	t.Cleanup(func() { global.GVA_CONFIG.AutoCode = old })
	global.GVA_CONFIG.AutoCode.Root = root
	global.GVA_CONFIG.AutoCode.Server = "server"
	for _, dir := range []string{"api", "router", "service", "initialize", "plugin"} {
		if err := os.CopyFS(filepath.Join(root, "server", dir), os.DirFS(filepath.Join(server, dir))); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"plugin.go", "api/enter.go", "router/enter.go", "service/enter.go", "initialize/gorm.go", "initialize/router.go"} {
		path := filepath.Join(root, "server/plugin/gva", name)
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			t.Fatal(err)
		}
		tmpl, err := template.ParseFiles(filepath.Join(server, "resource/plugin/server", name+".tpl"))
		if err != nil {
			t.Fatal(err)
		}
		file, err := os.Create(path)
		if err != nil {
			t.Fatal(err)
		}
		err = tmpl.Execute(file, map[string]string{"Package": "gva", "Module": "github.com/flipped-aurora/gin-vue-admin/server"})
		file.Close()
		if err != nil {
			t.Fatal(err)
		}
	}
	gen := filepath.Join(root, "server/plugin/gva/gen")
	if err := os.MkdirAll(gen, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(gen, "main.go"), []byte("package main\nfunc main() { g.ApplyBasic() }\n"), 0644); err != nil {
		t.Fatal(err)
	}
}
