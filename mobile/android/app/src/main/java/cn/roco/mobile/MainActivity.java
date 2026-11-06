package cn.roco.mobile;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.net.Uri;
import android.net.VpnService;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class MainActivity extends Activity {
    private WebView web;
    private TextView loading;
    private boolean pageFailed;
    private final List<String> packages = new ArrayList<>();
    private String appList = "[]";
    private String pendingPackage;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (RuntimeBridge.selectedPackage.isEmpty())
            RuntimeBridge.selectedPackage = getPreferences(MODE_PRIVATE).getString("game_package", "");
        loadApps();
        FrameLayout page = new FrameLayout(this);
        page.setBackgroundColor(0xfff4f6f8);
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        web = new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.addJavascriptInterface(new Bridge(), "Android");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                return !"http".equals(uri.getScheme()) || !"127.0.0.1".equals(uri.getHost()) || uri.getPort() != RuntimeBridge.port;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!pageFailed) loading.setVisibility(View.GONE);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showStartupFailure("页面加载失败，请重新打开助手。" + error.getDescription());
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame()) showStartupFailure("本机页面返回错误 " + response.getStatusCode());
            }
        });
        page.addView(web, new FrameLayout.LayoutParams(-1, -1));
        loading = new TextView(this);
        loading.setGravity(Gravity.CENTER);
        loading.setTextColor(0xff334155);
        loading.setTextSize(16);
        loading.setPadding(32, 32, 32, 32);
        loading.setBackgroundColor(0xfff4f6f8);
        loading.setText("正在准备本机对战助手…");
        page.addView(loading, new FrameLayout.LayoutParams(-1, -1));
        setContentView(page);
        new Thread(() -> {
            try {
                int port = RuntimeBridge.start(this);
                ui.post(() -> { if (!isDestroyed()) web.loadUrl("http://127.0.0.1:" + port + "/mobile"); });
            } catch (Throwable error) {
                ui.post(() -> showStartupFailure("本机引擎启动失败。" + error.getMessage()));
            }
        }, "roco-backend-start").start();
    }

    private void showStartupFailure(String message) {
        pageFailed = true;
        RuntimeBridge.status("error", message);
        if (!isDestroyed()) {
            loading.setText(message);
            loading.setVisibility(View.VISIBLE);
        }
    }

    private void loadApps() {
        Intent launchers = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> installed = getPackageManager().queryIntentActivities(launchers, 0);
        installed.sort(Comparator.comparing(app -> app.loadLabel(getPackageManager()).toString()));
        JSONArray result = new JSONArray();
        for (ResolveInfo app : installed) {
            String name = app.activityInfo.packageName;
            if (name.equals(getPackageName()) || packages.contains(name)) continue;
            packages.add(name);
            try {
                JSONObject item = new JSONObject();
                item.put("package", name);
                item.put("label", app.loadLabel(getPackageManager()).toString());
                result.put(item);
            } catch (org.json.JSONException error) { throw new IllegalStateException(error); }
        }
        appList = result.toString();
    }

    private void authorize(String selected) {
        if ("stopping".equals(RuntimeBridge.state)) {
            RuntimeBridge.message = "正在结束上次采集，请稍后重新开始。";
            return;
        }
        if (!packages.contains(selected)) {
            RuntimeBridge.status("error", "请选择已安装的游戏应用");
            return;
        }
        if ("running".equals(RuntimeBridge.state) || "starting".equals(RuntimeBridge.state)) {
            RuntimeBridge.message = "采集已启动。更换游戏前，请先停止当前采集。";
            return;
        }
        pendingPackage = selected;
        RuntimeBridge.selectedPackage = selected;
        getPreferences(MODE_PRIVATE).edit().putString("game_package", selected).apply();
        Intent permission = VpnService.prepare(this);
        if (permission != null) startActivityForResult(permission, 10); else startVpn();
    }

    private void startVpn() {
        RuntimeBridge.status("starting", "正在连接所选游戏");
        startForegroundService(new Intent(this, CaptureService.class).putExtra("package", pendingPackage));
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 11);
    }

    private void overlayPermission() {
        if (!Settings.canDrawOverlays(this))
            startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName())));
        else if ("running".equals(RuntimeBridge.state))
            startService(new Intent(this, CaptureService.class).setAction(CaptureService.OVERLAY));
    }

    private void launchGame(String name) {
        if (!packages.contains(name)) return;
        Intent intent = getPackageManager().getLaunchIntentForPackage(name);
        if (intent != null) startActivity(intent);
        else RuntimeBridge.message = "无法打开所选应用，请从系统桌面打开游戏。";
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 10) {
            if (result == RESULT_OK) startVpn();
            else RuntimeBridge.status("denied", "VPN 授权未通过，请允许连接后重试。");
        }
    }

    @Override protected void onResume() {
        super.onResume();
        if (Settings.canDrawOverlays(this) && "running".equals(RuntimeBridge.state))
            startService(new Intent(this, CaptureService.class).setAction(CaptureService.OVERLAY));
    }

    @Override protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        if (web != null) web.destroy();
        super.onDestroy();
    }

    public final class Bridge {
        @JavascriptInterface public String status() {
            try {
                JSONObject result = new JSONObject(RuntimeBridge.status());
                result.put("overlay_allowed", Settings.canDrawOverlays(MainActivity.this));
                result.put("vpn_authorized", VpnService.prepare(MainActivity.this) == null);
                return result.toString();
            } catch (org.json.JSONException error) { throw new IllegalStateException(error); }
        }
        @JavascriptInterface public void startCapture(String name) { ui.post(() -> authorize(name)); }
        @JavascriptInterface public void stopCapture() {
            ui.post(() -> startService(new Intent(MainActivity.this, CaptureService.class).setAction(CaptureService.STOP)));
        }
        @JavascriptInterface public void requestOverlay() { ui.post(MainActivity.this::overlayPermission); }
        @JavascriptInterface public void launchGame(String name) { ui.post(() -> MainActivity.this.launchGame(name)); }
        @JavascriptInterface public String listApps() { return appList; }
        @JavascriptInterface public void copyDiagnostics(String text) {
            if (text == null || text.length() > 65536) return;
            ui.post(() -> {
                getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("洛克助手诊断", text));
                Toast.makeText(MainActivity.this, "诊断已复制", Toast.LENGTH_SHORT).show();
            });
        }
    }
}
