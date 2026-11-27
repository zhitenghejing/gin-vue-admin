package system

import (
	"context"
	"strings"
	"testing"

	"github.com/flipped-aurora/gin-vue-admin/server/model/system/request"
)

func TestAutoCodeTemplatePreview(t *testing.T) {
	setupAutoCode(t)
	ctx := context.Background()
	if err := AutoCodePackage.Create(ctx, &request.SysAutoCodePackageCreate{Template: "plugin", PackageName: "gva"}); err != nil {
		t.Fatal(err)
	}
	info := request.AutoCode{Package: "gva", PackageName: "sample", HumpPackageName: "sample", StructName: "Sample", Abbreviation: "sample", Description: "Sample", TableName: "samples", GenerateServer: true, GvaModel: true}
	if err := info.Pretreatment(); err != nil {
		t.Fatal(err)
	}
	preview, err := AutoCodeTemplate.Preview(ctx, info)
	if err != nil {
		t.Fatal(err)
	}
	if len(preview) == 0 {
		t.Fatal("expected generated preview files")
	}
	for name, code := range preview {
		if !strings.HasPrefix(code, "```") {
			t.Fatalf("%s: missing code fence", name)
		}
	}
	info.Package = "missing"
	if _, err := AutoCodeTemplate.Preview(ctx, info); err == nil {
		t.Fatal("missing package must fail")
	}
}
