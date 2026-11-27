package system

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/flipped-aurora/gin-vue-admin/server/global"
	model "github.com/flipped-aurora/gin-vue-admin/server/model/system"
	"github.com/flipped-aurora/gin-vue-admin/server/model/system/request"
	"github.com/glebarez/sqlite"
	"gorm.io/gorm"
)

func setupAutoCode(t *testing.T) {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	server := filepath.Clean(filepath.Join(filepath.Dir(file), "../.."))
	root := t.TempDir()
	oldConfig, oldDB := global.GVA_CONFIG.AutoCode, global.GVA_DB
	t.Cleanup(func() { global.GVA_CONFIG.AutoCode, global.GVA_DB = oldConfig, oldDB })
	global.GVA_CONFIG.AutoCode.Root = root
	global.GVA_CONFIG.AutoCode.Server = "server"
	global.GVA_CONFIG.AutoCode.Web = "web/src"
	global.GVA_CONFIG.AutoCode.Module = "github.com/flipped-aurora/gin-vue-admin/server"
	for _, dir := range []string{"resource", "api", "router", "service", "plugin", "initialize"} {
		if err := os.CopyFS(filepath.Join(root, "server", dir), os.DirFS(filepath.Join(server, dir))); err != nil {
			t.Fatal(err)
		}
	}
	db, err := gorm.Open(sqlite.Open(filepath.Join(root, "test.db")), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { sqlDB.Close() })
	if err := db.AutoMigrate(&model.SysAutoCodePackage{}, &model.SysAutoCodeHistory{}); err != nil {
		t.Fatal(err)
	}
	global.GVA_DB = db
}

func TestAutoCodePackageCreate(t *testing.T) {
	for _, kind := range []string{"package", "plugin"} {
		t.Run(kind, func(t *testing.T) {
			setupAutoCode(t)
			info := request.SysAutoCodePackageCreate{Template: kind, PackageName: "gva"}
			if err := AutoCodePackage.Create(context.Background(), &info); err != nil {
				t.Fatal(err)
			}
			var stored model.SysAutoCodePackage
			if err := global.GVA_DB.First(&stored, "package_name = ?", "gva").Error; err != nil {
				t.Fatal(err)
			}
			if stored.Template != kind {
				t.Fatalf("got template %q", stored.Template)
			}
			path := filepath.Join(global.GVA_CONFIG.AutoCode.Root, "server/api/v1/gva/enter.go")
			if kind == "plugin" {
				path = filepath.Join(global.GVA_CONFIG.AutoCode.Root, "server/plugin/gva/plugin.go")
			}
			if _, err := os.Stat(path); err != nil {
				t.Fatal(err)
			}
			if err := AutoCodePackage.Create(context.Background(), &info); err == nil {
				t.Fatal("duplicate package accepted")
			}
		})
	}
}

func TestAutoCodePackageTemplates(t *testing.T) {
	setupAutoCode(t)
	codes, injections, creates, err := AutoCodePackage.templates(context.Background(), model.SysAutoCodePackage{Template: "plugin", PackageName: "preview"}, request.AutoCode{Package: "preview", Module: global.GVA_CONFIG.AutoCode.Module}, true)
	if err != nil {
		t.Fatal(err)
	}
	if len(codes) == 0 || len(injections) == 0 || len(creates) == 0 {
		t.Fatalf("incomplete template plan: %d/%d/%d", len(codes), len(injections), len(creates))
	}
}
