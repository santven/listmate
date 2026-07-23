package com.pvkslabs.listmate;

import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.net.Uri;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onStart() {
        super.onStart();
        WebView webView = getBridge().getWebView();
        final WebViewClient original = webView.getWebViewClient();
        webView.setWebViewClient(new WebViewClient() {
            // Modern API (API 24+) — called for all URL navigations
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request.getUrl() != null) {
                    String host = request.getUrl().getHost();
                    if (host != null && (
                        host.equals("grocerlist.app") ||
                        host.endsWith(".grocerlist.app") ||
                        host.equals("accounts.google.com") ||
                        host.equals("oauth2.googleapis.com")
                    )) {
                        view.loadUrl(request.getUrl().toString());
                        return true; // We handle it — don't hand to system browser
                    }
                }
                return super.shouldOverrideUrlLoading(view, request);
            }

            // Legacy API fallback
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                Uri uri = Uri.parse(url);
                String host = uri.getHost();
                if (host != null && (
                    host.equals("grocerlist.app") ||
                    host.endsWith(".grocerlist.app") ||
                    host.equals("accounts.google.com") ||
                    host.equals("oauth2.googleapis.com")
                )) {
                    view.loadUrl(url);
                    return true;
                }
                return super.shouldOverrideUrlLoading(view, url);
            }
        });
    }
}
