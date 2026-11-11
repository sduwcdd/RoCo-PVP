package cn.roco.mobile;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.net.VpnService;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.os.*;
import android.provider.Settings;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.Set;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import hev.htproxy.TProxyService;

public final class CaptureService extends VpnService {
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ThreadPoolExecutor mirror = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(512));
    private final Set<String> ignoredFlows = ConcurrentHashMap.newKeySet();
    private final AtomicLong ignoredCount = new AtomicLong();
    private LocalSocks socks;
    private ParcelFileDescriptor tunnel;
    private volatile boolean active, stopping, analysisPaused, sampleActive;
    private String finalState = "stopped", finalMessage = "采集已停止";
    private View overlay;
    private WebView overlayWeb;
    private WindowManager windows;
    private WindowManager.LayoutParams overlayLayout;
    private boolean overlayExpanded;
    private PvpOverlay pvpOverlay;
    public static final String STOP = "cn.roco.mobile.STOP", OVERLAY = "cn.roco.mobile.OVERLAY";

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || STOP.equals(intent.getAction())) { shutdown("stopped", "已停止采集，游戏恢复直接联网"); return START_NOT_STICKY; }
        if (OVERLAY.equals(intent.getAction())) { if (active) showOverlay(); else stopSelf(); return START_NOT_STICKY; }
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("capture", "本机游戏采集", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, CaptureService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "capture").setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("洛克同机助手").setContentText("仅转发你选定的游戏；点击打开状态面板")
            .setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(null, "停止采集", stop).build()).build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, notification);
        String selected = intent.getStringExtra("package");
        if (!active && !stopping) lifecycle.execute(() -> startCapture(selected));
        return START_NOT_STICKY;
    }
    private void startCapture(String selected) {
        if (stopping || active) return;
        try {
            if (selected == null || selected.trim().isEmpty() || selected.equals(getPackageName())) throw new IOException("请先选择已安装的游戏应用");
            getPackageManager().getPackageInfo(selected, 0);
            RuntimeBridge.selectedPackage = selected;
            RuntimeBridge.transport = new org.json.JSONObject();
            RuntimeBridge.status("starting", "正在启动本机转发");
            RuntimeBridge.analysisState = "running";
            RuntimeBridge.analysisMessage = "";
            RuntimeBridge.start(this);
            RuntimeBridge.module().callAttr("reset_capture");
            sampleActive = true;
            TProxyService.TProxyIsRunning(); // Load and check JNI before establishing the VPN.
            String password = UUID.randomUUID().toString();
            socks = new LocalSocks(new LocalSocks.Protector() {
                public boolean tcp(Socket socket) { boolean ok = protect(socket); if (!ok) shutdown("error", "TCP 出口保护失败"); return ok; }
                public boolean udp(DatagramSocket socket) { boolean ok = protect(socket); if (!ok) shutdown("error", "UDP 出口保护失败"); return ok; }
            }, new LocalSocks.Mirror() {
                public boolean interested(String id) { return (!analysisPaused || sampleActive) && !ignoredFlows.contains(id); }
                public void data(String id, String host, int port, String direction, byte[] bytes) {
                    enqueue(() -> {
                        if (ignoredFlows.contains(id)) return;
                        if (!RuntimeBridge.module().callAttr("feed", id, host, port, direction, bytes).toBoolean()) {
                            try {
                                org.json.JSONObject state = new org.json.JSONObject(RuntimeBridge.module().callAttr("status").toString());
                                String reason = state.optString("error");
                                pauseAnalysis(reason.isEmpty() ? "解析数据不完整，请复制连接诊断" : reason);
                            } catch (org.json.JSONException error) { pauseAnalysis("解析状态格式异常，请复制连接诊断"); }
                            return;
                        }
                        String protocol = RuntimeBridge.module().callAttr("flow_protocol", id).toString();
                        if (("http".equals(protocol) || "tls".equals(protocol) || "other".equals(protocol)) && ignoredFlows.add(id))
                            ignoredCount.incrementAndGet();
                    });
                }
                public void closed(String id) {
                    enqueue(() -> {
                        RuntimeBridge.module().callAttr("close_flow", id);
                        ignoredFlows.remove(id);
                    });
                }
                public void failed(String message) { sampleGap(message); pauseAnalysis(message); }
            }, password);
            File config = new File(getFilesDir(), "tunnel.yml");
            String yaml = "tunnel:\n  name: roco\n  mtu: 1500\n  ipv4: 198.18.0.1\n  ipv6: 'fd00:726f:636f::1'\n" +
                "socks5:\n  address: 127.0.0.1\n  port: " + socks.port() + "\n  udp: 'udp'\n  username: roco\n  password: '" + password + "'\n" +
                "misc:\n  log-level: warn\n  max-session-count: 128\n";
            try (OutputStream output = new FileOutputStream(config)) { output.write(yaml.getBytes(StandardCharsets.UTF_8)); }
            if (stopping) return;
            Builder builder = new Builder().setSession("洛克同机助手").setMtu(1500)
                .addAddress("198.18.0.1", 32).addAddress("fd00:726f:636f::1", 128)
                .addRoute("0.0.0.0", 0).addRoute("::", 0)
                .addAllowedApplication(selected).setBlocking(false);
            ConnectivityManager connectivity = getSystemService(ConnectivityManager.class);
            LinkProperties network = connectivity.getLinkProperties(connectivity.getActiveNetwork());
            if (network == null || network.getDnsServers().isEmpty()) throw new IOException("当前网络没有可用 DNS，请先连接网络");
            for (InetAddress dns : network.getDnsServers()) builder.addDnsServer(dns);
            tunnel = builder.establish();
            if (tunnel == null) throw new IOException("VPN 授权已取消");
            if (!TProxyService.TProxyStartService(config.getAbsolutePath(), tunnel.getFd())) throw new IOException("原生转发器启动失败");
            Thread.sleep(400);
            if (stopping) return;
            if (!TProxyService.TProxyIsRunning()) throw new IOException("原生转发器提前退出");
            active = true;
            RuntimeBridge.capturePackage = selected;
            RuntimeBridge.module().callAttr("set_capture_state", true, "");
            RuntimeBridge.status("running", "已连接所选应用，请重新登录游戏并进入对战。");
            ui.post(this::watch); ui.post(this::showOverlay);
        } catch (Throwable e) { shutdown("error", e.getClass().getSimpleName() + ": " + e.getMessage()); }
    }
    private void enqueue(Runnable task) {
        if (stopping) return;
        try { mirror.execute(() -> { if (!stopping) try { task.run(); } catch (Exception e) { sampleGap("镜像异常: " + e.getMessage()); pauseAnalysis("解析失败: " + e.getMessage()); } }); }
        catch (RejectedExecutionException e) {
            sampleGap("镜像队列已满，协议样本存在缺口");
            pauseAnalysis("镜像队列已满；本次观测不完整，请停止采集后重新连接");
        }
    }
    private void sampleGap(String reason) {
        if (!sampleActive) return;
        sampleActive = false;
        try { lifecycle.execute(() -> RuntimeBridge.module().callAttr("sample_gap", reason)); }
        catch (RejectedExecutionException ignored) { }
    }
    private synchronized void pauseAnalysis(String reason) {
        if (stopping || analysisPaused) return;
        analysisPaused = true;
        RuntimeBridge.analysisState = "paused";
        RuntimeBridge.analysisMessage = reason;
        RuntimeBridge.message = "分析已暂停，游戏网络继续转发";
        // Only the parser stops. Tearing down a healthy VPN also breaks the game's TCP sessions.
        try { mirror.execute(() -> {
            try { RuntimeBridge.module().callAttr("pause_analysis", reason); }
            catch (Exception ignored) { }
        }); } catch (RejectedExecutionException ignored) { }
    }
    private void watch() {
        if (!active || stopping) return;
        updateTransport();
        refreshOverlayMode();
        if (!TProxyService.TProxyIsRunning() || socks == null || !socks.isRunning()) { shutdown("error", "转发器退出；已关闭 VPN 恢复直接联网"); return; }
        enqueue(() -> {
            try {
                org.json.JSONObject state = new org.json.JSONObject(RuntimeBridge.module().callAttr("status").toString());
                String mode = state.optString("mode", "pvp");
                if (!mode.equals(RuntimeBridge.mode)) {
                    RuntimeBridge.mode = mode;
                    ui.post(this::refreshOverlayMode);
                }
                org.json.JSONObject samples = state.optJSONObject("protocol_samples");
                sampleActive = samples != null && samples.optBoolean("active", false);
                if (!state.optBoolean("decoder_ready", false)) pauseAnalysis(state.optString("error", "解析器已停止"));
            } catch (org.json.JSONException e) { pauseAnalysis("解析器状态格式错误"); }
        });
        ui.postDelayed(this::watch, "pve".equals(RuntimeBridge.mode) ? 250 : 1000);
    }
    private void updateTransport() {
        if (socks == null) return;
        try {
            org.json.JSONObject snapshot = new org.json.JSONObject(socks.diagnostics());
            long[] stats = TProxyService.TProxyGetStats();
            snapshot.put("tun_packets_up", stats[0]);
            snapshot.put("tun_bytes_up", stats[1]);
            snapshot.put("tun_packets_down", stats[2]);
            snapshot.put("tun_bytes_down", stats[3]);
            snapshot.put("mirror_queue_depth", mirror.getQueue().size());
            snapshot.put("ignored_tcp_flows", ignoredCount.get());
            snapshot.put("native_running", TProxyService.TProxyIsRunning());
            RuntimeBridge.transport = snapshot;
        } catch (org.json.JSONException error) { throw new IllegalStateException(error); }
    }
    private synchronized void shutdown(String state, String message) {
        if (stopping) return;
        stopping = true;
        active = false;
        RuntimeBridge.analysisState = "stopped";
        finalState = state;
        finalMessage = message;
        RuntimeBridge.status("stopping", message);
        updateTransport();
        // Closing the TUN first immediately releases app routing, even if a worker is stuck.
        try { if (tunnel != null) tunnel.close(); } catch (IOException ignored) { }
        if (socks != null) socks.close();
        mirror.shutdownNow();
        lifecycle.execute(() -> {
            try { if (tunnel != null) tunnel.close(); } catch (IOException ignored) { }
            if (socks != null) socks.close();
            try { TProxyService.TProxyStopService(); } catch (Throwable ignored) { }
            try {
                mirror.awaitTermination(5, TimeUnit.SECONDS);
                RuntimeBridge.module().callAttr("set_capture_state", false, "error".equals(state) ? message : "");
            } catch (Throwable ignored) { }
            ui.post(() -> { removeOverlay(); stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); });
            lifecycle.shutdown();
        });
    }
    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
    private void showOverlay() {
        if (!active || overlay != null || pvpOverlay != null || !Settings.canDrawOverlays(this)) return;
        if ("pvp".equals(RuntimeBridge.mode)) {
            try {
                pvpOverlay = new PvpOverlay(this);
                pvpOverlay.show();
            } catch (RuntimeException error) {
                pvpOverlay = null;
                RuntimeBridge.message = "转发已运行，PVP悬浮窗创建失败: " + error.getMessage();
            }
            return;
        }
        windows = getSystemService(WindowManager.class);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        android.graphics.drawable.GradientDrawable background = new android.graphics.drawable.GradientDrawable();
        background.setColor(0xff163e35);
        background.setCornerRadius(dp(16));
        background.setStroke(dp(1), 0xffb8953f);
        panel.setBackground(background);
        panel.setClipToOutline(true);
        panel.setElevation(dp(8));
        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView handle = new TextView(this);
        handle.setTextColor(0xfffff7dc);
        handle.setTextSize(12);
        handle.setGravity(Gravity.CENTER);
        handle.setContentDescription("拖动助手标签，点按展开或收起");
        header.addView(handle, new LinearLayout.LayoutParams(0, dp(48), 1));
        Button collapse = new Button(this);
        collapse.setText("收起");
        collapse.setTextSize(12);
        collapse.setPadding(0, 0, 0, 0);
        collapse.setContentDescription("收起为边缘标签");
        header.addView(collapse, new LinearLayout.LayoutParams(dp(56), dp(48)));
        Button dismiss = new Button(this);
        dismiss.setText("×");
        dismiss.setPadding(0, 0, 0, 0);
        dismiss.setContentDescription("关闭悬浮面板，继续采集");
        header.addView(dismiss, new LinearLayout.LayoutParams(dp(48), dp(48)));
        panel.addView(header);
        overlayWeb = new WebView(this);
        overlayWeb.setBackgroundColor(0xfff5f3eb);
        overlayWeb.getSettings().setJavaScriptEnabled(true);
        overlayWeb.getSettings().setDomStorageEnabled(true);
        overlayWeb.getSettings().setAllowFileAccess(false);
        overlayWeb.getSettings().setAllowContentAccess(false);
        overlayWeb.addJavascriptInterface(new OverlayStatus(), "Android");
        overlayWeb.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                android.net.Uri uri = request.getUrl();
                return !"http".equals(uri.getScheme()) || !"127.0.0.1".equals(uri.getHost()) || uri.getPort() != RuntimeBridge.port;
            }
        });
        panel.addView(overlayWeb, new LinearLayout.LayoutParams(-1, 0));
        overlayLayout = new WindowManager.LayoutParams(dp(48), dp(48),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT);
        overlayLayout.gravity = Gravity.TOP | Gravity.START;
        android.content.SharedPreferences prefs = getSharedPreferences("overlay", MODE_PRIVATE);
        overlayLayout.x = prefs.getInt("x", dp(8));
        overlayLayout.y = prefs.getInt("y", dp(96));
        Runnable resize = () -> {
            if (overlay == null) return;
            int screenWidth = getResources().getDisplayMetrics().widthPixels;
            int screenHeight = getResources().getDisplayMetrics().heightPixels;
            overlayLayout.width = overlayExpanded ? Math.min(dp(360), screenWidth - dp(16)) : dp(48);
            int height = Math.max(dp(48), screenHeight - dp(24));
            overlayLayout.height = overlayExpanded ? height : dp(48);
            overlayWeb.getLayoutParams().height = Math.max(0, height - dp(48));
            overlayWeb.setVisibility(overlayExpanded ? View.VISIBLE : View.GONE);
            collapse.setVisibility(overlayExpanded ? View.VISIBLE : View.GONE);
            dismiss.setVisibility(overlayExpanded ? View.VISIBLE : View.GONE);
            handle.setText(overlayExpanded ? "洛克助手 · 拖动" : "洛克\n助手");
            if (overlayExpanded) {
                overlayWeb.onResume();
                if (overlayWeb.getUrl() == null)
                    overlayWeb.loadUrl("http://127.0.0.1:" + RuntimeBridge.port + "/mobile?overlay=1");
            } else overlayWeb.onPause();
            overlayLayout.x = Math.max(0, Math.min(screenWidth - overlayLayout.width, overlayLayout.x));
            overlayLayout.y = Math.max(0, Math.min(screenHeight - overlayLayout.height, overlayLayout.y));
            windows.updateViewLayout(panel, overlayLayout);
        };
        handle.setOnClickListener(view -> { overlayExpanded = !overlayExpanded; resize.run(); });
        collapse.setOnClickListener(view -> { overlayExpanded = false; resize.run(); });
        dismiss.setOnClickListener(view -> removeOverlay());
        handle.setOnTouchListener(new View.OnTouchListener() {
            float x, y;
            int startX, startY;
            boolean dragged;
            final int slop = ViewConfiguration.get(CaptureService.this).getScaledTouchSlop();
            public boolean onTouch(View view, MotionEvent event) {
                switch (event.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        x = event.getRawX(); y = event.getRawY();
                        startX = overlayLayout.x; startY = overlayLayout.y;
                        dragged = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        float dx = event.getRawX() - x, dy = event.getRawY() - y;
                        if (Math.abs(dx) + Math.abs(dy) > slop) dragged = true;
                        if (dragged) {
                            int width = getResources().getDisplayMetrics().widthPixels;
                            int height = getResources().getDisplayMetrics().heightPixels;
                            overlayLayout.x = Math.max(0, Math.min(width - overlayLayout.width, startX + (int)dx));
                            overlayLayout.y = Math.max(0, Math.min(height - overlayLayout.height, startY + (int)dy));
                            windows.updateViewLayout(panel, overlayLayout);
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (!dragged) view.performClick();
                        prefs.edit().putInt("x", overlayLayout.x).putInt("y", overlayLayout.y).apply();
                        return true;
                    case MotionEvent.ACTION_CANCEL:
                        return true;
                    default:
                        return false;
                }
            }
        });
        try {
            windows.addView(panel, overlayLayout);
            overlay = panel;
            resize.run();
        } catch (RuntimeException error) {
            if (overlay == null) { overlayWeb.destroy(); overlayWeb = null; }
            else removeOverlay();
            RuntimeBridge.message = "转发已运行，悬浮窗创建失败: " + error.getMessage();
        }
    }
    private void removeOverlay() {
        if (pvpOverlay != null) {
            pvpOverlay.close();
            pvpOverlay = null;
        }
        if (overlay == null) return;
        windows.removeView(overlay);
        overlay = null;
        overlayLayout = null;
        overlayWeb.destroy();
        overlayWeb = null;
    }
    public static final class OverlayStatus {
        @JavascriptInterface public String status() { return RuntimeBridge.status(); }
        @JavascriptInterface public String listApps() { return "[]"; }
    }
    private void refreshOverlayMode() {
        if ((pvpOverlay != null && !"pvp".equals(RuntimeBridge.mode)) ||
            (overlay != null && "pvp".equals(RuntimeBridge.mode))) {
            removeOverlay();
            showOverlay();
        }
    }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (overlay != null || pvpOverlay != null) { removeOverlay(); showOverlay(); }
    }
    @Override public void onRevoke() { shutdown("revoked", "系统已撤销 VPN 授权；采集停止"); }
    @Override public void onDestroy() {
        shutdown("stopped", "采集服务已停止");
        RuntimeBridge.capturePackage = "";
        RuntimeBridge.status(finalState, finalMessage);
        removeOverlay();
        super.onDestroy();
    }
}
