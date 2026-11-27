//go:build !embedweb

package webui

import "net/http"

const Enabled = false

// Wrap leaves the standalone API server unchanged in development builds.
func Wrap(api http.Handler, routerPrefix string) (http.Handler, error) {
	return api, nil
}
