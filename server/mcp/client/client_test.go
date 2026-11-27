package client

import (
	"context"
	"net/http/httptest"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func TestClientRoundTrip(t *testing.T) {
	srv := server.NewMCPServer("test-server", "1.0.0")
	srv.AddTool(mcp.NewTool("echo", mcp.WithString("text", mcp.Required())),
		func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			text, err := request.RequireString("text")
			if err != nil {
				return nil, err
			}
			return mcp.NewToolResultText(text), nil
		})
	httpSrv := httptest.NewServer(server.NewStreamableHTTPServer(srv))
	defer httpSrv.Close()
	c, err := NewClient(httpSrv.URL, "test-client", "1.0.0", "test-server")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	tools, err := c.ListTools(context.Background(), mcp.ListToolsRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(tools.Tools) != 1 || tools.Tools[0].Name != "echo" {
		t.Fatalf("unexpected tools: %+v", tools.Tools)
	}
	request := mcp.CallToolRequest{}
	request.Params.Name = "echo"
	request.Params.Arguments = map[string]any{"text": "hello"}
	result, err := c.CallTool(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError || len(result.Content) != 1 {
		t.Fatalf("unexpected result: %+v", result)
	}
	content, ok := result.Content[0].(mcp.TextContent)
	if !ok || content.Text != "hello" {
		t.Fatalf("unexpected content: %+v", result.Content)
	}
	if c, err := NewClient(httpSrv.URL, "test-client", "1.0.0", "wrong-name"); err == nil {
		c.Close()
		t.Fatal("expected server identity mismatch")
	}
}
