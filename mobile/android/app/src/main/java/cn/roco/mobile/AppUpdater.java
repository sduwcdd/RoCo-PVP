package cn.roco.mobile;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Application-scoped worker keeps update IO independent from capture and Activity lifetime. */
final class AppUpdater {
    static final String RELEASES = "https://api.github.com/repos/sduwcdd/RoCo-PVP/releases?per_page=100";
    private static final String ASSET_PREFIX = "https://github.com/sduwcdd/RoCo-PVP/releases/download/";
    private static AppUpdater instance;
    private final Context context;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final File directory;
    private JSONObject candidate;
    private String state = "idle", message = "点击检查更新";
    private long downloaded, size;
    private boolean busy;

    static synchronized AppUpdater get(Context context) {
        if (instance == null) instance = new AppUpdater(context.getApplicationContext());
        return instance;
    }

    private AppUpdater(Context context) {
        this.context = context;
        directory = new File(context.getCacheDir(), "update");
        busy = true;
        worker.execute(() -> {
            try {
                File metadata = new File(directory, "verified.json");
                if (metadata.isFile()) {
                    JSONObject saved;
                    try (InputStream input = new FileInputStream(metadata)) { saved = new JSONObject(readText(input, 65536)); }
                    validateManifest(saved, current().getLongVersionCode());
                    verify(apk(), saved);
                    synchronized (this) { candidate = saved; size = saved.getLong("size"); downloaded = size; }
                    status("ready", "已校验更新，可继续安装");
                }
            } catch (Exception ignored) { status("idle", "点击检查更新"); }
            finally { finish(); check(); }
        });
    }

    private PackageInfo current() throws PackageManager.NameNotFoundException {
        return context.getPackageManager().getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
    }

    synchronized String snapshot() {
        JSONObject result = new JSONObject();
        try {
            result.put("state", state).put("message", message).put("busy", busy);
            result.put("currentVersion", current().versionName).put("currentVersionCode", current().getLongVersionCode());
            result.put("downloaded", downloaded).put("size", size).put("progress", size > 0 ? downloaded * 100 / size : 0);
            if (candidate != null) result.put("versionName", candidate.getString("versionName")).put("versionCode", candidate.getLong("versionCode"));
        } catch (Exception error) { throw new IllegalStateException(error); }
        return result.toString();
    }

    private synchronized boolean begin() { if (busy) return false; busy = true; return true; }
    private synchronized void finish() { busy = false; }
    private synchronized void status(String state, String message) { this.state = state; this.message = message; }

    void check() {
        if (!begin()) return;
        status("checking", "正在检查 GitHub 发布…");
        worker.execute(() -> {
            try {
                JSONArray releases = new JSONArray(fetchText(RELEASES, 4 * 1024 * 1024));
                JSONObject newest = null;
                long installed = current().getLongVersionCode();
                for (int i = 0; i < releases.length(); i++) {
                    JSONObject release = releases.getJSONObject(i);
                    if (release.optBoolean("draft") || !release.optString("tag_name").startsWith("android-v")) continue;
                    JSONArray assets = release.getJSONArray("assets");
                    JSONObject manifestAsset = asset(assets, "android-update.json");
                    if (manifestAsset == null) continue;
                    String manifestUrl = manifestAsset.getString("browser_download_url");
                    validateAssetUrl(manifestUrl, release.getString("tag_name"), "android-update.json");
                    JSONObject manifest = new JSONObject(fetchText(manifestUrl, 65536));
                    if (manifest.optLong("versionCode") <= installed) continue;
                    validateManifest(manifest, installed);
                    JSONObject binary = asset(assets, manifest.getString("apk"));
                    if (binary == null || binary.getLong("size") != manifest.getLong("size")) throw new IOException("发布 APK 与更新清单不匹配");
                    String url = binary.getString("browser_download_url");
                    validateAssetUrl(url, release.getString("tag_name"), manifest.getString("apk"));
                    manifest.put("downloadUrl", url);
                    if (newest == null || manifest.getLong("versionCode") > newest.getLong("versionCode")) newest = manifest;
                }
                synchronized (this) {
                    candidate = newest;
                    size = newest == null ? 0 : newest.getLong("size");
                    downloaded = 0;
                }
                if (newest == null) status("current", "已是最新版本");
                else {
                    boolean ready = false;
                    try { verify(apk(), newest); ready = true; } catch (Exception ignored) { }
                    if (ready) { persist(newest); synchronized (this) { downloaded = size; } }
                    status(ready ? "ready" : "available", ready ? "更新已校验，可安装" : "发现新版本，可下载更新");
                }
            } catch (Exception error) {
                boolean ready = false;
                try { if (candidate != null) { verify(apk(), candidate); ready = true; } } catch (Exception ignored) { }
                status(ready ? "ready" : "error", "检查失败：" + error.getMessage() + (ready ? "；已校验安装包仍可安装" : ""));
            }
            finally { finish(); }
        });
    }

    void download() {
        if (!begin()) return;
        final JSONObject selected;
        synchronized (this) { selected = candidate; downloaded = 0; }
        if (selected == null) { finish(); return; }
        status("downloading", "正在下载更新…");
        worker.execute(() -> {
            File partial = new File(directory, "download.apk");
            try {
                if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("无法建立更新目录");
                long expected = selected.getLong("size");
                HttpURLConnection connection = connect(selected.getString("downloadUrl"));
                try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(partial)) {
                    long declared = connection.getContentLengthLong();
                    if (declared > 0 && declared != expected) throw new IOException("下载长度与清单不匹配");
                    byte[] buffer = new byte[65536];
                    int count;
                    long total = 0;
                    while ((count = input.read(buffer)) != -1) {
                        total += count;
                        if (total > expected) throw new IOException("下载超过清单长度");
                        output.write(buffer, 0, count);
                        synchronized (this) { downloaded = total; }
                    }
                    output.getFD().sync();
                } finally { connection.disconnect(); }
                status("verifying", "正在校验文件、版本和安装签名…");
                verify(partial, selected);
                if (!partial.renameTo(apk())) throw new IOException("无法保存已校验安装包");
                persist(selected);
                status("ready", "更新已校验，请点击安装");
            } catch (Exception error) { status("error", "下载失败：" + error.getMessage()); }
            finally { partial.delete(); finish(); }
        });
    }

    void install(Activity activity) {
        if (!begin()) return;
        final JSONObject selected;
        synchronized (this) { selected = candidate; }
        worker.execute(() -> {
            try {
                if (selected == null) throw new IOException("请先检查并下载更新");
                verify(apk(), selected);
                activity.runOnUiThread(() -> {
                    try {
                        if (activity.isDestroyed()) return;
                        if (!context.getPackageManager().canRequestPackageInstalls()) {
                            activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + context.getPackageName())));
                            status("ready", "请允许此来源安装，返回助手后再次点击安装");
                        } else {
                            Uri uri = Uri.parse("content://" + context.getPackageName() + ".updates/update.apk");
                            Intent intent = new Intent(Intent.ACTION_INSTALL_PACKAGE).setDataAndType(uri, "application/vnd.android.package-archive")
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).putExtra(Intent.EXTRA_RETURN_RESULT, true);
                            intent.setClipData(android.content.ClipData.newRawUri("更新安装包", uri));
                            activity.startActivityForResult(intent, 12);
                            status("ready", "请在系统页面确认安装，取消后可再次点击安装");
                        }
                    } catch (Exception error) { status("ready", "无法打开安装页面：" + error.getMessage()); }
                    finally { finish(); }
                });
            } catch (Exception error) { status("error", "安装校验失败：" + error.getMessage()); finish(); }
        });
    }

    void installationResult(int result) {
        status("ready", result == Activity.RESULT_CANCELED ? "安装已取消，安装包已保留，可再次点击安装"
            : result == Activity.RESULT_OK ? "安装已完成，请重新打开助手查看版本" : "系统安装未完成，安装包已保留，可再次点击安装");
    }

    static JSONObject asset(JSONArray assets, String name) throws Exception {
        for (int i = 0; i < assets.length(); i++) if (name.equals(assets.getJSONObject(i).optString("name"))) return assets.getJSONObject(i);
        return null;
    }

    static void validateAssetUrl(String value, String tag, String name) throws IOException {
        Uri uri = Uri.parse(value);
        if (!value.startsWith(ASSET_PREFIX) || !"https".equals(uri.getScheme()) || !"github.com".equals(uri.getHost()) || uri.getPort() != -1
            || uri.getQuery() != null || uri.getFragment() != null || uri.getUserInfo() != null
            || !("/sduwcdd/RoCo-PVP/releases/download/" + tag + "/" + name).equals(uri.getPath()))
            throw new IOException("更新地址不属于此仓库发布");
    }

    static void validateManifest(JSONObject manifest, long installed) throws Exception {
        Object code = manifest.get("versionCode"), minimum = manifest.get("minSdk"), length = manifest.get("size");
        if (!(code instanceof Integer || code instanceof Long) || !(minimum instanceof Integer || minimum instanceof Long)
            || !(length instanceof Integer || length instanceof Long)) throw new IOException("更新清单数值格式错误");
        if (manifest.getLong("versionCode") <= installed || manifest.getLong("versionCode") > Integer.MAX_VALUE
            || !"cn.roco.mobile".equals(manifest.getString("packageName")) || manifest.getLong("minSdk") < 29
            || manifest.getLong("minSdk") > Build.VERSION.SDK_INT || manifest.getLong("size") <= 0 || manifest.getLong("size") > 1024L * 1024 * 1024
            || manifest.getString("versionName").isEmpty() || !manifest.getString("apk").matches("[A-Za-z0-9._-]+\\.apk")
            || !manifest.getString("sha256").matches("[a-fA-F0-9]{64}") || !manifest.getString("signerSha256").matches("[a-fA-F0-9]{64}"))
            throw new IOException("更新清单不兼容或字段无效");
    }

    File apk() { return new File(directory, "verified.apk"); }

    android.os.ParcelFileDescriptor openVerified() throws Exception {
        JSONObject saved;
        try (InputStream input = new FileInputStream(new File(directory, "verified.json"))) { saved = new JSONObject(readText(input, 65536)); }
        verify(apk(), saved);
        return android.os.ParcelFileDescriptor.open(apk(), android.os.ParcelFileDescriptor.MODE_READ_ONLY);
    }

    private void persist(JSONObject manifest) throws Exception {
        File temporary = new File(directory, "verified.json.tmp");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(manifest.toString().getBytes(StandardCharsets.UTF_8)); output.getFD().sync();
        }
        if (!temporary.renameTo(new File(directory, "verified.json"))) throw new IOException("无法保存更新状态");
    }

    void verify(File file, JSONObject manifest) throws Exception {
        validateManifest(manifest, current().getLongVersionCode());
        if (!file.isFile() || file.length() != manifest.getLong("size")) throw new IOException("安装包长度校验失败，请重新下载");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        if (!hex(digest.digest()).equalsIgnoreCase(manifest.getString("sha256"))) throw new IOException("安装包 SHA-256 校验失败");
        PackageInfo archive = context.getPackageManager().getPackageArchiveInfo(file.getPath(), PackageManager.GET_SIGNING_CERTIFICATES);
        validateArchive(archive, manifest, context.getPackageName());
        Signature[] existing = current().signingInfo.getApkContentsSigners();
        Signature[] incoming = archive.signingInfo == null ? new Signature[0] : archive.signingInfo.getApkContentsSigners();
        validateSignatures(existing, incoming, manifest.getString("signerSha256"));
    }

    static void validateArchive(PackageInfo archive, JSONObject manifest, String packageName) throws Exception {
        if (archive == null || !packageName.equals(archive.packageName) || archive.getLongVersionCode() != manifest.getLong("versionCode")
            || !manifest.getString("versionName").equals(archive.versionName) || archive.applicationInfo == null
            || archive.applicationInfo.minSdkVersion != manifest.getInt("minSdk")) throw new IOException("APK 应用标识或版本不匹配");
    }

    static void validateSignatures(Signature[] existing, Signature[] incoming, String signer) throws Exception {
        if (existing.length != 1 || incoming.length != 1 || !existing[0].equals(incoming[0])
            || !hex(MessageDigest.getInstance("SHA-256").digest(incoming[0].toByteArray())).equalsIgnoreCase(signer))
            throw new IOException("安装签名不兼容，无法保留数据覆盖升级；请使用与本机相同签名的发布安装包");
    }

    static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder();
        for (byte item : bytes) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }

    private static HttpURLConnection connect(String address) throws Exception {
        URL url = new URL(address);
        for (int redirect = 0; redirect < 6; redirect++) {
            if (!"https".equals(url.getProtocol()) || url.getUserInfo() != null || (url.getPort() != -1 && url.getPort() != 443)) throw new IOException("更新连接必须使用 HTTPS");
            String host = url.getHost();
            if (!host.equals("api.github.com") && !host.equals("github.com") && !host.equals("release-assets.githubusercontent.com")
                && !host.equals("objects.githubusercontent.com")) throw new IOException("更新重定向目标无效");
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(20000); connection.setReadTimeout(30000); connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("User-Agent", "RoCo-Mobile-Updater");
            int response = connection.getResponseCode();
            if (response == 200) return connection;
            String location = connection.getHeaderField("Location"); connection.disconnect();
            if (response < 300 || response > 399 || location == null) throw new IOException("GitHub HTTP " + response);
            url = new URL(url, location);
        }
        throw new IOException("更新重定向次数过多");
    }

    private static String fetchText(String url, int limit) throws Exception {
        HttpURLConnection connection = connect(url);
        try (InputStream input = connection.getInputStream()) { return readText(input, limit); }
        finally { connection.disconnect(); }
    }

    private static String readText(InputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int count;
        while ((count = input.read(buffer)) != -1) {
            if (output.size() + count > limit) throw new IOException("更新元数据过大");
            output.write(buffer, 0, count);
        }
        return output.toString(StandardCharsets.UTF_8.name());
    }
}
