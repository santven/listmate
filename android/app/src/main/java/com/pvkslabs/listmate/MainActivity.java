package com.pvkslabs.listmate;

import android.content.Intent;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleVoiceIntent(getIntent());
    }

    @Override
    public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleVoiceIntent(intent);
    }

    private void handleVoiceIntent(Intent intent) {
        if (intent != null) {
            String itemName = null;
            String listName = null;
            
            if (intent.getExtras() != null) {
                itemName = intent.getStringExtra("itemName");
                listName = intent.getStringExtra("listName");
            }
            
            if (intent.getData() != null) {
                android.net.Uri uri = intent.getData();
                if (itemName == null && uri.getQueryParameter("itemName") != null) {
                    itemName = uri.getQueryParameter("itemName");
                }
                if (listName == null && uri.getQueryParameter("listName") != null) {
                    listName = uri.getQueryParameter("listName");
                }
            }
            

            if (itemName != null && !itemName.isEmpty()) {
                final String safeItem = itemName.replace("'", "\\'");
                final String safeList = listName != null ? listName.replace("'", "\\'") : "";
                
                final String jsCode = "window.pendingVoiceAction = {itemName: '" + safeItem + "', listName: '" + safeList + "'}; " +
                                      "if (window.dispatchEvent) window.dispatchEvent(new CustomEvent('onVoiceAction', {detail: window.pendingVoiceAction}));";
                
                // Give the webview a moment to initialize if this is a cold boot
                new android.os.Handler().postDelayed(() -> {
                    if (bridge != null && bridge.getWebView() != null) {
                        bridge.getWebView().evaluateJavascript(jsCode, null);
                    }
                }, 2000);
            }
        }
    }
}
