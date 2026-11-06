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
    private volatile boolean active, stopping;
    private String finalState = "stopped", finalMessage = "采集已停止";
    private View overlay;
    private WebView overlayWeb;
    private WindowManager windows;
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
            RuntimeBridge.start(this);
            RuntimeBridge.module().callAttr("reset_capture");
            TProxyService.TProxyIsRunning(); // Load and check JNI before establishing the VPN.
            String password = UUID.randomUUID().toString();
            socks = new LocalSocks(new LocalSocks.Protector() {
                public boolean tcp(Socket socket) { boolean ok = protect(socket); if (!ok) shutdown("error", "TCP 出口保护失败"); return ok; }
                public boolean udp(DatagramSocket socket) { boolean ok = protect(socket); if (!ok) shutdown("error", "UDP 出口保护失败"); return ok; }
            }, new LocalSocks.Mirror() {
                public boolean interested(String id) { return !ignoredFlows.contains(id); }
                public void data(String id, String host, int port, String direction, byte[] bytes) {
                    enqueue(() -> {
                        if (ignoredFlows.contains(id)) return;
                        if (!RuntimeBridge.module().callAttr("feed", id, host, port, direction, bytes).toBoolean()) {
                            shutdown("error", "解析队列拒绝数据；已停止 VPN，避免显示不完整战况");
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
        try { mirror.execute(() -> { if (!stopping) try { task.run(); } catch (Throwable e) { shutdown("error", "解析失败: " + e.getMessage()); } }); }
        catch (RejectedExecutionException e) { shutdown("error", "镜像队列已满；已停止 VPN"); }
    }
    private void watch() {
        if (!active || stopping) return;
        updateTransport();
        if (!TProxyService.TProxyIsRunning() || socks == null || !socks.isRunning()) { shutdown("error", "转发器退出；已关闭 VPN 恢复直接联网"); return; }
        enqueue(() -> {
            try {
                org.json.JSONObject state = new org.json.JSONObject(RuntimeBridge.module().callAttr("status").toString());
                if (!state.optBoolean("decoder_ready", false)) shutdown("error", "解析器已停止: " + state.optString("error"));
            } catch (org.json.JSONException e) { shutdown("error", "解析器状态格式错误"); }
        });
        ui.postDelayed(this::watch, 1000);
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
    private void showOverlay() {
        if (!active || overlay != null || !Settings.canDrawOverlays(this)) return;
        windows = getSystemService(WindowManager.class);
        float density = getResources().getDisplayMetrics().density;
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setBackgroundColor(0xff101b28);
        TextView handle = new TextView(this);
        handle.setText("洛克助手　·　拖动 / 点按收起");
        handle.setTextSize(12);
        handle.setTextColor(0xffd8e5ec);
        handle.setPadding((int)(12 * density), (int)(8 * density), (int)(12 * density), (int)(8 * density));
        handle.setContentDescription("拖动悬浮窗，点按展开或收起");
        panel.addView(handle);
        overlayWeb = new WebView(this);
        overlayWeb.getSettings().setJavaScriptEnabled(true);
        overlayWeb.getSettings().setDomStorageEnabled(true);
        overlayWeb.getSettings().setAllowFileAccess(false);
        overlayWeb.getSettings().setAllowContentAccess(false);
        overlayWeb.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                android.net.Uri uri = request.getUrl();
                return !"http".equals(uri.getScheme()) || !"127.0.0.1".equals(uri.getHost()) || uri.getPort() != RuntimeBridge.port;
            }
        });
        overlayWeb.loadUrl("http://127.0.0.1:" + RuntimeBridge.port + "/mobile?overlay=1");
        int contentHeight = Math.min((int)(380 * density), Math.max((int)(160 * density), screenHeight - (int)(96 * density)));
        panel.addView(overlayWeb, new LinearLayout.LayoutParams(-1, contentHeight));
        WindowManager.LayoutParams layout = new WindowManager.LayoutParams(Math.min((int)(320 * density), screenWidth - (int)(24 * density)), -2,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        layout.gravity = Gravity.TOP | Gravity.START; layout.x = 20; layout.y = 100;
        handle.setOnClickListener(view -> {
            boolean expanded = overlayWeb.getVisibility() == View.VISIBLE;
            overlayWeb.setVisibility(expanded ? View.GONE : View.VISIBLE);
            handle.setText(expanded ? "洛克助手　·　点按展开" : "洛克助手　·　拖动 / 点按收起");
        });
        handle.setOnTouchListener(new View.OnTouchListener() {
            float x,y; int startX,startY;
            public boolean onTouch(View v, android.view.MotionEvent event) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) { x=event.getRawX(); y=event.getRawY(); startX=layout.x; startY=layout.y; return true; }
                if (event.getAction() == MotionEvent.ACTION_MOVE) {
                    layout.x = Math.max(0, Math.min(screenWidth - layout.width, startX + (int)(event.getRawX() - x)));
                    layout.y = Math.max(0, Math.min(screenHeight - handle.getHeight(), startY + (int)(event.getRawY() - y)));
                    windows.updateViewLayout(panel, layout);
                    return true;
                }
                if (event.getAction() == MotionEvent.ACTION_UP) {
                    if (Math.abs(event.getRawX() - x) + Math.abs(event.getRawY() - y) < 12 * density) v.performClick();
                    return true;
                }
                return false;
            }
        });
        try { windows.addView(panel, layout); overlay = panel; }
        catch (RuntimeException e) { RuntimeBridge.message = "转发已运行，悬浮窗创建失败: " + e.getMessage(); }
    }
    private void removeOverlay() { if (overlay != null) { windows.removeView(overlay); overlay = null; overlayWeb.destroy(); overlayWeb = null; } }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (overlay != null) { removeOverlay(); showOverlay(); }
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
