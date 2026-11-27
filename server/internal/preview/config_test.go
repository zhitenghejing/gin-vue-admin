package preview

import (
	"testing"

	"github.com/flipped-aurora/gin-vue-admin/server/config"
)

func TestPreviewConfigurationStaysLocal(t *testing.T) {
	var cfg config.Server
	cfg.System.ListenHost = "0.0.0.0"
	cfg.System.DbType = "mysql"
	cfg.System.UseRedis = true
	cfg.System.UseMongo = true
	cfg.Sqlite.Dbname = "another-database"
	cfg.DBList = []config.SpecializedDB{{}}
	cfg.AutoCode.Root = "/checkout"
	cfg.AutoCode.Server = "../../checkout"
	data := t.TempDir()
	if err := Configure(&cfg, data, 43210); err != nil {
		t.Fatal(err)
	}
	if cfg.System.ListenHost != "127.0.0.1" || cfg.System.Addr != 43210 || cfg.System.DbType != "sqlite" || cfg.System.UseRedis || cfg.System.UseMongo || len(cfg.DBList) != 0 {
		t.Fatal("preview configuration escaped local dependencies")
	}
	if cfg.Sqlite.Path != data || cfg.Sqlite.Dbname != "preview" || cfg.AutoCode.Server != "server" || cfg.AutoCode.Root == "/checkout" {
		t.Fatal("preview paths escaped owned runtime")
	}
	cfg.Sqlite.Dbname = ""
	if err := Configure(&cfg, data, 43210); err != nil || cfg.Sqlite.Dbname != "" {
		t.Fatal("uninitialized previews must retain the initialization flow")
	}
	if err := Configure(&cfg, "relative/path", 43210); err == nil {
		t.Fatal("relative preview data path accepted")
	}
	if err := Configure(&cfg, data, 0); err == nil {
		t.Fatal("invalid preview port accepted")
	}
}
