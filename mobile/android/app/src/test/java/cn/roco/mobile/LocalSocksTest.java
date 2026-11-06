package cn.roco.mobile;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;

/** Standalone regression check: javac LocalSocks.java LocalSocksTest.java; java -ea ... */
public final class LocalSocksTest {
    static final String PASSWORD = "test-private-password";
    static void check(boolean ok, String description) { if (!ok) throw new AssertionError(description); }
    static Socket authenticate(int port, String password) throws Exception {
        Socket socket = new Socket("127.0.0.1", port); socket.setSoTimeout(5000);
        OutputStream out = socket.getOutputStream(); DataInputStream in = new DataInputStream(socket.getInputStream());
        out.write(new byte[]{5,1,2}); check(in.readUnsignedShort() == 0x0502, "method");
        byte[] secret = password.getBytes(StandardCharsets.UTF_8);
        out.write(new byte[]{1,4,'r','o','c','o',(byte)secret.length}); out.write(secret);
        check(in.readUnsignedShort() == (password.equals(PASSWORD) ? 0x0100 : 0x0101), "authentication");
        return socket;
    }
    static InetSocketAddress request(Socket socket, int command, InetAddress address, int port) throws Exception {
        OutputStream out = socket.getOutputStream(); byte[] raw = address.getAddress();
        out.write(new byte[]{5,(byte)command,0,(byte)(raw.length == 4 ? 1 : 4)}); out.write(raw); out.write(port >>> 8); out.write(port & 255);
        DataInputStream in = new DataInputStream(socket.getInputStream()); check(in.readUnsignedByte()==5,"version");
        check(in.readUnsignedByte()==0,"command success"); check(in.readUnsignedByte()==0,"reserved");
        int type=in.readUnsignedByte(); byte[] host=new byte[type==1?4:16]; in.readFully(host);
        return new InetSocketAddress(InetAddress.getByAddress(host),in.readUnsignedShort());
    }
    public static void main(String[] args) throws Exception {
        AtomicInteger protectedTcp = new AtomicInteger(), protectedUdp = new AtomicInteger();
        Map<String,ByteArrayOutputStream> copies = new ConcurrentHashMap<>(); CountDownLatch ended = new CountDownLatch(1);
        AtomicBoolean interested = new AtomicBoolean(true);
        LocalSocks.Protector protect = new LocalSocks.Protector() { public boolean tcp(Socket s) { protectedTcp.incrementAndGet(); return true; } public boolean udp(DatagramSocket s) { protectedUdp.incrementAndGet(); return true; } };
        LocalSocks.Mirror mirror = new LocalSocks.Mirror() {
            public boolean interested(String id) { return interested.get(); }
            public void data(String id,String host,int port,String dir,byte[] data) { synchronized(copies) { copies.computeIfAbsent(dir,k->new ByteArrayOutputStream()).write(data,0,data.length); } }
            public void closed(String id) { ended.countDown(); }
        };
        ExecutorService echo = Executors.newCachedThreadPool();
        try (LocalSocks relay = new LocalSocks(protect,mirror,PASSWORD);
             ServerSocket tcp = new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));
             DatagramSocket udp4 = new DatagramSocket(new InetSocketAddress("127.0.0.1",0));
             DatagramSocket udp6 = new DatagramSocket(new InetSocketAddress("::1",0))) {
            try (Socket wrong = authenticate(relay.port(),"wrong")) { check(wrong.getInputStream().read()==-1,"wrong password closes"); }
            byte[] body = new byte[200000]; new Random(2026).nextBytes(body);
            Future<?> target = echo.submit(() -> { try (Socket s=tcp.accept()) { s.getInputStream().transferTo(s.getOutputStream()); } catch(IOException e){throw new RuntimeException(e);} });
            try (Socket client = authenticate(relay.port(), PASSWORD)) {
                check(tcp.getLocalPort()!=8195,"regression must cover a non-8195 port");
                request(client,1,InetAddress.getByName("127.0.0.1"),tcp.getLocalPort());
                Future<?> sender=echo.submit(()->{try{client.getOutputStream().write(body);client.shutdownOutput();}catch(IOException e){throw new RuntimeException(e);}});
                check(Arrays.equals(body,client.getInputStream().readAllBytes()),"TCP bytes/half close"); sender.get();
            }
            target.get(); check(ended.await(5,TimeUnit.SECONDS),"flow close callback");
            check(Arrays.equals(body,copies.get("c2s").toByteArray()),"upstream mirror"); check(Arrays.equals(body,copies.get("s2c").toByteArray()),"downstream mirror");
            check(((Number)relay.diagnostics().get("tcp_bytes_up")).longValue()==body.length,"TCP up diagnostics");
            check(((Number)relay.diagnostics().get("tcp_bytes_down")).longValue()==body.length,"TCP down diagnostics");
            interested.set(false);
            Future<?> ignoredTarget = echo.submit(() -> {
                try (Socket socket = tcp.accept()) { socket.getInputStream().transferTo(socket.getOutputStream()); }
                catch (IOException error) { throw new RuntimeException(error); }
            });
            try (Socket client = authenticate(relay.port(), PASSWORD)) {
                request(client, 1, InetAddress.getByName("127.0.0.1"), tcp.getLocalPort());
                byte[] ignoredBody = "unrelated traffic remains connected".getBytes(StandardCharsets.UTF_8);
                client.getOutputStream().write(ignoredBody);
                client.shutdownOutput();
                check(Arrays.equals(ignoredBody, client.getInputStream().readAllBytes()), "ignored flow still forwards");
            }
            ignoredTarget.get();
            check(copies.get("c2s").size() == body.length && copies.get("s2c").size() == body.length, "ignored flow not copied");
            for (DatagramSocket remote : new DatagramSocket[]{udp4,udp6}) {
                Future<?> responder=echo.submit(()->{try {byte[] buffer=new byte[2048];DatagramPacket p=new DatagramPacket(buffer,buffer.length);remote.receive(p);remote.send(p);}catch(IOException e){throw new RuntimeException(e);}});
                try(Socket control=authenticate(relay.port(),PASSWORD);DatagramSocket client=new DatagramSocket()) {
                    InetSocketAddress endpoint=request(control,3,InetAddress.getByName("0.0.0.0"),0);
                    ByteArrayOutputStream encoded=new ByteArrayOutputStream();encoded.write(new byte[]{0,0,0});byte[] address=remote.getLocalAddress().getAddress();encoded.write(address.length==4?1:4);encoded.write(address);encoded.write(remote.getLocalPort()>>>8);encoded.write(remote.getLocalPort()&255);encoded.write("dns-probe".getBytes(StandardCharsets.UTF_8));
                    byte[] sent=encoded.toByteArray();client.send(new DatagramPacket(sent,sent.length,endpoint));client.setSoTimeout(5000);byte[] buffer=new byte[2048];DatagramPacket response=new DatagramPacket(buffer,buffer.length);client.receive(response);
                    check(Arrays.equals(sent,Arrays.copyOf(buffer,response.getLength())),"UDP dual stack response");
                }
                responder.get();
            }
            check(protectedTcp.get()==2 && protectedUdp.get()==2,"every upstream socket protected");
            int previousPort=relay.port();relay.close();
            try (Socket ignored=new Socket("127.0.0.1",previousPort)) { throw new AssertionError("listener remains open"); } catch(ConnectException expected) { }
        } finally { echo.shutdownNow(); }
        System.out.println("PASS non-8195 TCP 200000 bytes, bidirectional mirror, ignored-flow forwarding, diagnostics, half close, IPv4+IPv6 UDP, auth, protect, shutdown");
    }
}
