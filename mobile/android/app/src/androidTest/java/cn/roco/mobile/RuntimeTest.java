package cn.roco.mobile;

import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import hev.htproxy.TProxyService;

/** Device checks use the packaged encrypted resources and real Android Python runtime. */
public final class RuntimeTest {
    @Test public void testNativeLibraryLoads() { assertFalse(TProxyService.TProxyIsRunning()); }
    @Test public void testSharedEngineAndHttpStart() throws Exception {
        int port = RuntimeBridge.start(InstrumentationRegistry.getInstrumentation().getTargetContext());
        assertTrue(port > 0);
        JSONObject status = new JSONObject(read(port, "/api/mobile/status"));
        assertTrue(status.toString(), status.getBoolean("decoder_ready"));
        assertFalse(status.getBoolean("capture_running"));
        assertTrue(read(port, "/mobile").contains("html"));
        assertTrue(read(port, "/api/hud/snapshot").startsWith("{"));
    }
    private String read(int port, String path) throws IOException {
        HttpURLConnection connection = (HttpURLConnection)new URL("http://127.0.0.1:"+port+path).openConnection();
        connection.setConnectTimeout(10000); connection.setReadTimeout(30000);
        try {
            assertEquals(200, connection.getResponseCode());
            try(InputStream input=connection.getInputStream(); ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192];int n;while((n=input.read(buffer))!=-1) bytes.write(buffer,0,n);
                return new String(bytes.toByteArray(),StandardCharsets.UTF_8);
            }
        } finally { connection.disconnect(); }
    }
}
