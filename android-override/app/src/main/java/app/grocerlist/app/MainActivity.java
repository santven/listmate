package app.grocerlist.app;

import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.net.Uri;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onStart() {
        super.onStart();
        WebView webView = getBridge().getWebView();
        final WebViewClient original = webView.getWebViewClient();
        webView.setWebViewClient(new WebViewClient() {
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
                    // Keep in WebView — don't hand off to system browser
                    return false;
                }
                // Delegate to original Capacitor handler
                if (original != null) {
                    return original.shouldOverrideUrlLoading(view, url);
                }
                return super.shouldOverrideUrlLoading(view, url);
            }
        });
    }
}
