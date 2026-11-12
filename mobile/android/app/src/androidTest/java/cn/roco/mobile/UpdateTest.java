package cn.roco.mobile;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.net.URL;
import java.security.MessageDigest;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class UpdateTest {
    private interface Checked { void run() throws Exception; }
    private void rejects(Checked action, String message) throws Exception {
        try { action.run(); fail("Expected rejection"); }
        catch (java.io.IOException error) { assertTrue(error.toString(), error.getMessage().contains(message)); }
    }
    private JSONObject manifest() throws Exception {
        return new JSONObject().put("versionCode", 999).put("versionName", "test").put("packageName", "cn.roco.mobile")
            .put("minSdk", 29).put("apk", "roco.apk").put("sha256", AppUpdater.hex(new byte[32])).put("size", 100).put("signerSha256", AppUpdater.hex(new byte[32]));
    }
    @Test public void validatesManifestAndRepositoryBinding() throws Exception {
        JSONObject value = manifest();
        AppUpdater.validateManifest(value, 10);
        rejects(() -> AppUpdater.validateManifest(new JSONObject(value.toString()).put("apk", "../roco.apk"), 10), "清单");
        rejects(() -> AppUpdater.validateManifest(new JSONObject(value.toString()).put("versionCode", 10), 10), "清单");
        rejects(() -> AppUpdater.validateManifest(new JSONObject(value.toString()).put("versionCode", 999.5), 10), "数值");
        rejects(() -> AppUpdater.validateManifest(new JSONObject(value.toString()).put("minSdk", 1000), 10), "清单");
        String url = "https://github.com/sduwcdd/RoCo-PVP/releases/download/android-v0.11.0-internal/roco.apk";
        AppUpdater.validateAssetUrl(url, "android-v0.11.0-internal", "roco.apk");
        rejects(() -> AppUpdater.validateAssetUrl(url.replace("sduwcdd", "other"), "android-v0.11.0-internal", "roco.apk"), "地址");
        rejects(() -> AppUpdater.validateAssetUrl(url, "android-v0.12.0-internal", "roco.apk"), "地址");
    }
    @Test public void validatesRealApkMetadataAndSignature() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        PackageInfo installed = context.getPackageManager().getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
        PackageInfo archive = context.getPackageManager().getPackageArchiveInfo(installed.applicationInfo.sourceDir, PackageManager.GET_SIGNING_CERTIFICATES);
        JSONObject value = manifest().put("versionCode", installed.getLongVersionCode()).put("versionName", installed.versionName);
        AppUpdater.validateArchive(archive, value, context.getPackageName());
        rejects(() -> AppUpdater.validateArchive(archive, new JSONObject(value.toString()).put("versionCode", 12345), context.getPackageName()), "版本");
        rejects(() -> AppUpdater.validateArchive(archive, value, "other.package"), "标识");
        Signature[] signatures = installed.signingInfo.getApkContentsSigners();
        String signer = AppUpdater.hex(MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()));
        AppUpdater.validateSignatures(signatures, archive.signingInfo.getApkContentsSigners(), signer);
        rejects(() -> AppUpdater.validateSignatures(signatures, new Signature[]{new Signature(new byte[]{1, 2, 3})}, signer), "签名");
        rejects(() -> AppUpdater.validateSignatures(signatures, signatures, AppUpdater.hex(new byte[32])), "签名");
    }

    @Test public void cnbPointerSelectsUpdatesAndStopsAtCurrentVersion() throws Exception {
        JSONObject value = manifest().put("downloadUrl", "https://cnb.cool/sduwcgg/roco-pvp/-/releases/download/android-v0.12-internal/roco.apk");
        ArrayList<String> requests = new ArrayList<>();
        AppUpdater.MetadataFetcher fetcher = (url, limit) -> {
            requests.add(url);
            assertEquals(AppUpdater.CNB_LATEST, url);
            return value.toString();
        };
        AppUpdater.UpdateSelection available = AppUpdater.findUpdate(10, fetcher);
        assertEquals("CNB", available.source);
        assertEquals(999, available.manifest.getLong("versionCode"));
        assertEquals("CNB", available.manifest.getString("source"));
        assertNull(AppUpdater.findUpdate(999, fetcher).manifest);
        assertNull(AppUpdater.findUpdate(1000, fetcher).manifest);
        assertEquals(3, requests.size());
    }

    @Test public void cnbFailureAndInvalidManifestFallBackToGithub() throws Exception {
        String tag = "android-v0.12-internal";
        String prefix = "https://github.com/sduwcdd/RoCo-PVP/releases/download/" + tag + "/";
        JSONObject value = manifest();
        JSONArray assets = new JSONArray().put(new JSONObject().put("name", "android-update.json").put("browser_download_url", prefix + "android-update.json"))
            .put(new JSONObject().put("name", "roco.apk").put("size", 100).put("browser_download_url", prefix + "roco.apk"));
        String releases = new JSONArray().put(new JSONObject().put("tag_name", tag).put("assets", assets)).toString();
        for (String invalid : new String[]{"unavailable", "{}", new JSONObject(value.toString()).put("downloadUrl", "https://cnb.cool/other/roco-pvp/-/releases/download/" + tag + "/roco.apk").toString(),
            new JSONObject(value.toString()).put("sha256", "invalid").put("downloadUrl", "https://cnb.cool/sduwcgg/roco-pvp/-/releases/download/" + tag + "/roco.apk").toString()}) {
            ArrayList<String> requests = new ArrayList<>();
            AppUpdater.UpdateSelection selected = AppUpdater.findUpdate(10, (url, limit) -> {
                requests.add(url);
                if (url.equals(AppUpdater.CNB_LATEST)) {
                    if (invalid.equals("unavailable")) throw new IOException("offline");
                    return invalid;
                }
                if (url.equals(AppUpdater.RELEASES)) return releases;
                assertEquals(prefix + "android-update.json", url);
                return value.toString();
            });
            assertEquals("GitHub 备用", selected.source);
            assertEquals(prefix + "roco.apk", selected.manifest.getString("downloadUrl"));
            assertEquals(AppUpdater.CNB_LATEST, requests.get(0));
            assertEquals(AppUpdater.RELEASES, requests.get(1));
        }
    }

    @Test public void cnbUrlsKeepRepositoryHttpsAndRedirectBoundaries() throws Exception {
        String url = "https://cnb.cool/sduwcgg/roco-pvp/-/releases/download/android-v0.12-internal/roco.apk";
        AppUpdater.validateCnbAssetUrl(url, "roco.apk");
        for (String invalid : new String[]{url.replace("sduwcgg", "sduwcdd"), url.replace("https:", "http:"), url + "?token=x", url + "#fragment",
            url.replace("/android-v0.12-internal/", "/../"), url.replace("/roco.apk", "/other.apk"), "https://example.com/roco.apk", ""})
            rejects(() -> AppUpdater.validateCnbAssetUrl(invalid, "roco.apk"), "地址");
        AppUpdater.validateConnectionUrl(new URL(url), true);
        AppUpdater.validateConnectionUrl(new URL("https://cdn.cnb.cool/asset?signature=x"), true);
        AppUpdater.validateConnectionUrl(new URL("https://release-assets.githubusercontent.com/asset?signature=x"), false);
        for (String invalid : new String[]{"https://cnb.cool.evil.example/asset", "https://api.cnb.cool/asset", "https://github.com/asset", "https://example.com/asset"})
            rejects(() -> AppUpdater.validateConnectionUrl(new URL(invalid), true), "目标");
        rejects(() -> AppUpdater.validateConnectionUrl(new URL("http://cnb.cool/asset"), true), "HTTPS");
        rejects(() -> AppUpdater.validateConnectionUrl(new URL("https://user@cnb.cool/asset"), true), "HTTPS");
        rejects(() -> AppUpdater.validateConnectionUrl(new URL("https://cnb.cool:8443/asset"), true), "HTTPS");
        rejects(() -> AppUpdater.validateConnectionUrl(new URL("https://cdn.cnb.cool/asset"), false), "目标");
    }
    @Test public void providerRejectsTraversalAndWrites() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        for (String path : new String[]{"/../update.apk", "/anything.apk", "/update.apk?path=other"}) {
            try { context.getContentResolver().openFileDescriptor(Uri.parse("content://cn.roco.mobile.updates" + path), "r"); fail("Invalid URI accepted"); }
            catch (SecurityException expected) { }
        }
        try { context.getContentResolver().openFileDescriptor(Uri.parse("content://cn.roco.mobile.updates/update.apk"), "w"); fail("Write accepted"); }
        catch (SecurityException expected) { }
    }

    @Test public void rejectsTruncatedAndCorruptDownloads() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        java.io.File sample = java.io.File.createTempFile("update-integrity-", ".apk", context.getCacheDir());
        try {
            try (java.io.FileOutputStream output = new java.io.FileOutputStream(sample)) { output.write(new byte[100]); }
            JSONObject value = manifest();
            rejects(() -> AppUpdater.get(context).verify(sample, new JSONObject(value.toString()).put("size", 101)), "长度");
            rejects(() -> AppUpdater.get(context).verify(sample, value), "SHA-256");
        } finally { assertTrue(sample.delete()); }
    }
}
