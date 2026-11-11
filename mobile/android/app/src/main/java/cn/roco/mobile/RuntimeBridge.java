package cn.roco.mobile;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import java.io.*;
import java.nio.file.*;

final class RuntimeBridge {
    static volatile String state = "idle", message = "尚未启动采集";
    static volatile int port;
    static volatile String selectedPackage = "", capturePackage = "";
    static volatile String analysisState = "stopped", analysisMessage = "";
    static volatile org.json.JSONObject transport = new org.json.JSONObject();
    static synchronized int start(Context context) throws IOException {
        if (port != 0) return port;
        File root = context.getFilesDir();
        File temporary = new File(root, "resources.rpk.tmp");
        try (InputStream in = context.getAssets().open("resources.rpk"); OutputStream out = new FileOutputStream(temporary)) {
            byte[] buffer = new byte[65536]; int size;
            while ((size = in.read(buffer)) != -1) out.write(buffer, 0, size);
        }
        Files.move(temporary.toPath(), new File(root, "resources.rpk").toPath(), StandardCopyOption.REPLACE_EXISTING);
        port = module().callAttr("start", root.getAbsolutePath()).toInt();
        if (port <= 0 || port > 65535) { port = 0; throw new IOException("Invalid local backend port"); }
        return port;
    }
    static PyObject module() { return Python.getInstance().getModule("roco_mobile"); }
    static String status() {
        try {
            org.json.JSONObject result = new org.json.JSONObject();
            result.put("state", state);
            result.put("message", message);
            result.put("selected_package", selectedPackage);
            result.put("capture_package", capturePackage);
            result.put("analysis_state", analysisState);
            result.put("analysis_message", analysisMessage);
            result.put("transport", transport);
            return result.toString();
        } catch (org.json.JSONException e) { throw new IllegalStateException(e); }
    }
    static void status(String next, String detail) { state = next; message = detail; }
}
