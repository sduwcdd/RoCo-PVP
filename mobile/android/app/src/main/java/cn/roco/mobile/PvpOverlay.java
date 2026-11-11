package cn.roco.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

/** Separate window bounds keep the uncovered game surface touchable. */
final class PvpOverlay {
    private final Context context;
    private final WindowManager windows;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final SharedPreferences preferences;
    private final List<Panel> panels = new ArrayList<>();
    private boolean closed;

    PvpOverlay(Context context) {
        this.context = context;
        windows = context.getSystemService(WindowManager.class);
        preferences = context.getSharedPreferences("pvp-overlay", Context.MODE_PRIVATE);
    }

    void show() {
        try {
            for (String side : new String[]{"my", "enemy", "history"}) {
                Panel panel = new Panel(side);
                panels.add(panel);
                panel.show();
            }
        } catch (RuntimeException error) {
            close();
            throw error;
        }
    }

    void close() {
        closed = true;
        for (Panel panel : panels) panel.close();
        panels.clear();
    }

    private int dp(int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    // All coordinates are window pixels, independent of the HTML viewport scale.
    static int[] measure(int width, int height, int gap, int sideLimit, int historyLimit, int header, String side, boolean expanded) {
        boolean landscape = width >= height;
        int sideWidth = Math.min(sideLimit, Math.max(header, (width - 4 * gap) * (landscape ? 27 : 46) / 100));
        int panelWidth = "history".equals(side)
            ? Math.min(historyLimit, landscape ? width - 2 * sideWidth - 4 * gap : width - 2 * gap)
            : sideWidth;
        panelWidth = Math.max(header, Math.min(width - 2 * gap, panelWidth));
        int panelHeight = "history".equals(side) ? Math.min(height * 36 / 100, header * 6) : height - 2 * gap - header * 2;
        if (!expanded) { panelWidth = Math.min(panelWidth, header * 3); panelHeight = header; }
        panelHeight = Math.max(header, Math.min(height - 2 * gap, panelHeight));
        int x = "my".equals(side) ? gap : "enemy".equals(side) ? width - panelWidth - gap : (width - panelWidth) / 2;
        int y = !landscape && "history".equals(side) ? header + 2 * gap : gap;
        return new int[]{panelWidth, panelHeight, x, Math.min(y, height - panelHeight)};
    }

    private final class Panel {
        final String side;
        final String title;
        final LinearLayout root;
        final TextView header;
        final WebView web;
        final WindowManager.LayoutParams layout;
        boolean attached, expanded, loaded;
        int contentHeight;
        float dragX = Float.NaN, dragY = Float.NaN;

        Panel(String side) {
            this.side = side;
            contentHeight = dp(48);
            title = "my".equals(side) ? "我方" : "enemy".equals(side) ? "敌方" : "回合记录";
            expanded = preferences.getBoolean(side + ".expanded", true);
            int color = "my".equals(side) ? 0xb32c6e9b : "enemy".equals(side) ? 0xb396493c : 0xb3274c47;
            root = new LinearLayout(context);
            root.setOrientation(LinearLayout.VERTICAL);
            GradientDrawable background = new GradientDrawable();
            background.setColor(color);
            background.setCornerRadius(dp(10));
            background.setStroke(dp(1), 0x66d5dfdd);
            root.setBackground(background);
            root.setClipToOutline(true);
            header = new TextView(context);
            header.setGravity(Gravity.CENTER_VERTICAL);
            header.setPadding(dp(10), 0, dp(6), 0);
            header.setTextSize(13);
            header.setTextColor(0xffffffff);
            header.setTypeface(null, android.graphics.Typeface.BOLD);
            header.setSingleLine(true);
            header.setClickable(true);
            header.setFocusable(true);
            header.setOnClickListener(view -> toggle());
            root.addView(header, new LinearLayout.LayoutParams(-1, dp(32)));
            web = new WebView(context);
            web.setBackgroundColor(0x00000000);
            web.getSettings().setJavaScriptEnabled(true);
            web.getSettings().setDomStorageEnabled(true);
            web.getSettings().setAllowFileAccess(false);
            web.getSettings().setAllowContentAccess(false);
            web.addJavascriptInterface(new ContentBridge(), "Android");
            web.setWebViewClient(new WebViewClient() {
                @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    android.net.Uri uri = request.getUrl();
                    return !"http".equals(uri.getScheme()) || !"127.0.0.1".equals(uri.getHost()) || uri.getPort() != RuntimeBridge.port;
                }
            });
            root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
            layout = new WindowManager.LayoutParams(1, 1, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
            layout.gravity = Gravity.TOP | Gravity.LEFT;
            layout.alpha = 0.78f;
            int slop = ViewConfiguration.get(context).getScaledTouchSlop();
            header.setOnTouchListener(new View.OnTouchListener() {
                float downX, downY;
                int startX, startY;
                boolean dragged;
                @Override public boolean onTouch(View view, MotionEvent event) {
                    switch (event.getActionMasked()) {
                        case MotionEvent.ACTION_DOWN:
                            downX = event.getRawX(); downY = event.getRawY();
                            startX = layout.x; startY = layout.y; dragged = false;
                            return true;
                        case MotionEvent.ACTION_MOVE:
                            float dx = event.getRawX() - downX, dy = event.getRawY() - downY;
                            if (Math.abs(dx) + Math.abs(dy) > slop) dragged = true;
                            if (dragged) {
                                int width = context.getResources().getDisplayMetrics().widthPixels;
                                int height = context.getResources().getDisplayMetrics().heightPixels;
                                layout.x = Math.max(0, Math.min(width - layout.width, startX + Math.round(dx)));
                                layout.y = Math.max(0, Math.min(height - layout.height, startY + Math.round(dy)));
                                dragX = (float)layout.x / Math.max(1, width - layout.width);
                                dragY = (float)layout.y / Math.max(1, height - layout.height);
                                windows.updateViewLayout(root, layout);
                            }
                            return true;
                        case MotionEvent.ACTION_UP:
                            if (!dragged) view.performClick();
                            return true;
                        case MotionEvent.ACTION_CANCEL:
                            return true;
                        default:
                            return false;
                    }
                }
            });
        }

        void show() {
            resize();
            windows.addView(root, layout);
            attached = true;
            updateContent();
        }

        void toggle() {
            expanded = !expanded;
            preferences.edit().putBoolean(side + ".expanded", expanded).apply();
            contentHeight = expanded ? dp(48) : 0;
            resize();
            updateContent();
        }

        void updateContent() {
            web.setVisibility(expanded ? View.VISIBLE : View.GONE);
            if (expanded && !loaded) {
                loaded = true;
                web.onResume();
                web.loadUrl("http://127.0.0.1:" + RuntimeBridge.port + "/mobile/pvp-panel.html?side=" + side);
            } else if (!expanded && loaded) {
                loaded = false;
                web.loadUrl("about:blank");
                web.onPause();
            }
        }

        void resize() {
            if (closed) return;
            int width = context.getResources().getDisplayMetrics().widthPixels;
            int height = context.getResources().getDisplayMetrics().heightPixels;
            int[] bounds = measure(width, height, dp(8), dp(260), dp(400), dp(32), side, expanded);
            layout.width = bounds[0];
            layout.height = expanded && contentHeight > 0 ? Math.min(bounds[1], dp(32) + contentHeight) : bounds[1];
            layout.x = Float.isNaN(dragX) ? bounds[2] : Math.round(dragX * Math.max(0, width - layout.width));
            layout.y = Float.isNaN(dragY) ? bounds[3] : Math.round(dragY * Math.max(0, height - layout.height));
            header.setText(title + (expanded ? "  ▾" : "  ▸"));
            header.setContentDescription(title + (expanded ? "，点按收起，长拖移动" : "，点按展开，长拖移动"));
            if (attached) windows.updateViewLayout(root, layout);
        }

        void close() {
            if (attached) windows.removeView(root);
            attached = false;
            web.removeJavascriptInterface("Android");
            web.stopLoading();
            web.destroy();
        }

        final class ContentBridge {
            @JavascriptInterface public String status() { return RuntimeBridge.status(); }
            @JavascriptInterface public void setContentHeight(double cssHeight) {
                if (!Double.isFinite(cssHeight) || cssHeight < 1 || cssHeight > 20000) return;
                ui.post(() -> {
                    if (closed || !attached || !expanded || !loaded) return;
                    int pixels = Math.max(1, (int)Math.ceil(cssHeight * context.getResources().getDisplayMetrics().density));
                    if (Math.abs(contentHeight - pixels) <= 1) return;
                    contentHeight = pixels;
                    resize();
                });
            }
        }
    }
}
