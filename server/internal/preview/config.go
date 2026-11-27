package preview

import (
	"fmt"
	"path/filepath"

	"github.com/flipped-aurora/gin-vue-admin/server/config"
)

// Configure keeps preview startup and config reloads on owned local resources.
func Configure(cfg *config.Server, dataDir string, port int) error {
	if !filepath.IsAbs(dataDir) {
		return fmt.Errorf("preview requires an absolute GVA_PREVIEW_DATA_DIR")
	}
	if port < 1 || port > 65535 {
		return fmt.Errorf("preview requires a valid GVA_PREVIEW_PORT")
	}
	cfg.System.ListenHost = "127.0.0.1"
	cfg.System.Addr = port
	cfg.System.RouterPrefix = ""
	cfg.System.DbType = "sqlite"
	cfg.System.OssType = "local"
	cfg.System.UseRedis = false
	cfg.System.UseMongo = false
	cfg.DBList = nil
	cfg.RedisList = nil
	cfg.Sqlite.Path = dataDir
	if cfg.Sqlite.Dbname != "" {
		cfg.Sqlite.Dbname = "preview"
	}
	cfg.Local.Path = "uploads/file"
	cfg.Local.StorePath = "uploads/file"
	cfg.AutoCode.Root, _ = filepath.Abs("..")
	cfg.AutoCode.Server = "server"
	cfg.AutoCode.Web = "web/src"
	return nil
}
