package cn.roco.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Separate test APK UID, so its traffic really traverses the selected-app VPN. */
public final class ProbeActivity extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        String token=getIntent().getStringExtra("token");
        int protocolBytes = getIntent().getIntExtra("tgcp_bytes", 0);
        int lateProtocolBytes = getIntent().getIntExtra("tgcp_late_bytes", 0);
        new Thread(() -> {
            String result="ok";
            Socket protocol = null;
            Socket lateProtocol = null;
            try {
                ConnectivityManager manager=getSystemService(ConnectivityManager.class);
                long deadline=System.currentTimeMillis()+10000;
                NetworkCapabilities network;
                do { network=manager.getNetworkCapabilities(manager.getActiveNetwork());
                    if(network!=null&&network.hasTransport(NetworkCapabilities.TRANSPORT_VPN))break;
                    Thread.sleep(100);
                } while(System.currentTimeMillis()<deadline);
                if(network==null||!network.hasTransport(NetworkCapabilities.TRANSPORT_VPN))throw new IOException("Probe UID did not acquire VPN network");
                Thread.sleep(1000);
                try(Socket tcp=new Socket()) {
                    tcp.connect(new InetSocketAddress("10.0.2.2",18080),10000);tcp.setSoTimeout(10000);
                    tcp.getOutputStream().write("GET /native-probe HTTP/1.0\r\nHost: probe\r\n\r\n".getBytes(StandardCharsets.US_ASCII));
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[2048];int n;while((n=tcp.getInputStream().read(buffer))!=-1)bytes.write(buffer,0,n);
                    String response = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
                    if (!response.contains("roco-native-forwarding-ok"))
                        throw new IOException("TCP fixture response mismatch, bytes=" + bytes.size() + ", response=" + response.substring(0, Math.min(160, response.length())));
                }
                try(DatagramSocket udp=new DatagramSocket()) {
                    udp.setSoTimeout(10000);byte[] data="roco-udp-probe".getBytes(StandardCharsets.US_ASCII);
                    udp.send(new DatagramPacket(data,data.length,InetAddress.getByName("10.0.2.2"),18081));
                    byte[] buffer=new byte[2048];DatagramPacket p=new DatagramPacket(buffer,buffer.length);udp.receive(p);
                    if(!Arrays.equals(data,Arrays.copyOf(buffer,p.getLength())))throw new IOException("UDP response mismatch");
                }
                if (protocolBytes > 0) {
                    if (protocolBytes > 1024 * 1024) throw new IOException("Oversized protocol fixture");
                    protocol = new Socket();
                    protocol.connect(new InetSocketAddress("10.0.2.2", 18082), 10000);
                    protocol.setSoTimeout(15000);
                    new DataInputStream(protocol.getInputStream()).readFully(new byte[protocolBytes]);
                }
                if (lateProtocolBytes > 0) {
                    if (lateProtocolBytes > 1024 * 1024) throw new IOException("Oversized late-key fixture");
                    lateProtocol = new Socket();
                    lateProtocol.connect(new InetSocketAddress("10.0.2.2", 18083), 10000);
                    lateProtocol.setSoTimeout(15000);
                    new DataInputStream(lateProtocol.getInputStream()).readFully(new byte[lateProtocolBytes]);
                }
            }catch(Throwable e){result=e.toString();}
            sendBroadcast(new Intent("cn.roco.mobile.PROBE_RESULT").setPackage("cn.roco.mobile").putExtra("token",token).putExtra("result",result));
            if (protocol != null) {
                try {
                    // Keep the game flow open while the instrumentation reads the live decoder/HUD.
                    while (protocol.getInputStream().read() != -1) { }
                } catch (IOException ignored) { }
                finally { try { protocol.close(); } catch (IOException ignored) { } }
            }
            if (lateProtocol != null) try { lateProtocol.close(); } catch (IOException ignored) { }
            runOnUiThread(this::finish);
        },"vpn-probe").start();
    }
}
