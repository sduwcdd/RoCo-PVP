package cn.roco.mobile;

import android.content.*;
import android.net.VpnService;
import android.os.Build;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import java.util.UUID;
import java.util.concurrent.*;
import hev.htproxy.TProxyService;

/** Requires explicit VPN consent and local TCP/UDP echo fixtures on emulator host. */
public final class VpnForwardingTest {
    @Test public void forwardsOtherAppThroughNativeTunAndStops() throws Exception {
        Context target=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assumeTrue("VPN must be authorized before this integration test", VpnService.prepare(target)==null);
        String probePackage=InstrumentationRegistry.getInstrumentation().getContext().getPackageName();
        int protocolBytes = Integer.parseInt(InstrumentationRegistry.getArguments().getString("tgcp_bytes", "0"));
        int lateProtocolBytes = Integer.parseInt(InstrumentationRegistry.getArguments().getString("tgcp_late_bytes", "0"));
        String token=UUID.randomUUID().toString();CountDownLatch received=new CountDownLatch(1);String[] result={"no response"};
        BroadcastReceiver receiver=new BroadcastReceiver(){public void onReceive(Context c,Intent i){if(token.equals(i.getStringExtra("token"))){result[0]=i.getStringExtra("result");received.countDown();}}};
        if(Build.VERSION.SDK_INT>=33)target.registerReceiver(receiver,new IntentFilter("cn.roco.mobile.PROBE_RESULT"),Context.RECEIVER_EXPORTED);
        else target.registerReceiver(receiver,new IntentFilter("cn.roco.mobile.PROBE_RESULT"));
        target.startActivity(new Intent(target,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            target.startForegroundService(new Intent(target,CaptureService.class).putExtra("package",probePackage));
            long end=System.currentTimeMillis()+60000;
            while(!"running".equals(RuntimeBridge.state)&&!"error".equals(RuntimeBridge.state)&&System.currentTimeMillis()<end)Thread.sleep(100);
            assertEquals(RuntimeBridge.message,"running",RuntimeBridge.state);
            assertEquals("selected application mismatch", probePackage, RuntimeBridge.capturePackage);
            target.startActivity(new Intent().setClassName(probePackage,"cn.roco.mobile.ProbeActivity").putExtra("token",token)
                .putExtra("tgcp_bytes", protocolBytes).putExtra("tgcp_late_bytes", lateProtocolBytes).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            assertTrue("probe timeout",received.await(40,TimeUnit.SECONDS));assertEquals(RuntimeBridge.message,"ok",result[0]);
            long[] stats=TProxyService.TProxyGetStats();assertTrue("native TUN transmitted no packets",stats[0]>0);assertTrue("native TUN received no packets",stats[2]>0);
            org.json.JSONObject decoder = new org.json.JSONObject(RuntimeBridge.module().callAttr("status").toString());
            assertTrue("ordinary HTTP must preserve decoder readiness", decoder.getBoolean("decoder_ready"));
            assertEquals("ordinary HTTP must preserve the VPN", "running", RuntimeBridge.state);
            if (protocolBytes > 0) {
                int expectedRecords = lateProtocolBytes > 0 ? 2 : 1;
                long decodedBy = System.currentTimeMillis() + 10000;
                while ((decoder.optInt("schema_business_records") < expectedRecords || !hasProtocolPort()) && decoder.getBoolean("decoder_ready") && System.currentTimeMillis() < decodedBy) {
                    Thread.sleep(100);
                    decoder = new org.json.JSONObject(RuntimeBridge.module().callAttr("status").toString());
                }
                assertTrue(decoder.toString(), decoder.getBoolean("decoder_ready"));
                assertTrue(decoder.toString(), decoder.getInt("key_hits") >= expectedRecords);
                assertTrue(decoder.toString(), decoder.getInt("schema_business_records") >= expectedRecords);
                assertTrue(decoder.toString(), decoder.getInt("active_game_flows") >= 1);
                assertTrue(decoder.toString(), decoder.getBoolean("battle_detected"));
                assertTrue(decoder.toString(), decoder.getInt("unknown_nonbattle_records") >= 1);
                if (lateProtocolBytes > 0) assertTrue(decoder.toString(), decoder.getInt("missing_key_records") >= 1);
                org.json.JSONObject snapshot = new org.json.JSONObject(RuntimeBridge.module().callAttr("hud_snapshot").toString());
                org.json.JSONObject runtime = snapshot.getJSONObject("payload").getJSONObject("runtime");
                assertEquals("fixture battle identity changed", 90261106L, runtime.getLong("battleId"));
                assertEquals("fixture own roster", 1, runtime.getJSONArray("myTeam").length());
                assertEquals("fixture opposing roster", 1, runtime.getJSONArray("enemyTeam").length());
                assertTrue(RuntimeBridge.transport.toString(), hasProtocolPort());
                System.out.println("NONSTANDARD_PORT_TGCP_DEVICE_RESULT " + decoder);
                System.out.println("SYNTHETIC_FIXTURE_HUD battleId=90261106 myTeam=1 enemyTeam=1");
            }
        } finally {
            target.startService(new Intent(target,CaptureService.class).setAction(CaptureService.STOP));target.unregisterReceiver(receiver);
            long end=System.currentTimeMillis()+10000;while(TProxyService.TProxyIsRunning()&&System.currentTimeMillis()<end)Thread.sleep(100);
            assertFalse("native forwarding still active after stop",TProxyService.TProxyIsRunning());
            while ("stopping".equals(RuntimeBridge.state) && System.currentTimeMillis() < end) Thread.sleep(100);
            assertEquals("service did not finish stopping", "stopped", RuntimeBridge.state);
            assertEquals("stopped capture still claims an application", "", RuntimeBridge.capturePackage);
        }
    }
    private boolean hasProtocolPort() {
        org.json.JSONObject ports = RuntimeBridge.transport.optJSONObject("tcp_port_counts");
        return ports != null && ports.has("18082");
    }
}
