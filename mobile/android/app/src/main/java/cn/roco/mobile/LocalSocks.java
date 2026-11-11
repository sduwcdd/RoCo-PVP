package cn.roco.mobile;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** Local authenticated SOCKS5 relay. The VPN must protect every upstream socket. */
public final class LocalSocks implements AutoCloseable {
    public interface Protector { boolean tcp(Socket s); boolean udp(DatagramSocket s); }
    public interface Mirror {
        default boolean interested(String id) { return true; }
        void data(String id, String host, int port, String direction, byte[] data);
        void closed(String id);
        default void failed(String message) { }
    }
    private final Protector protector;
    private final Mirror mirror;
    private final String password;
    private final ServerSocket listener;
    private final Set<Closeable> sockets = ConcurrentHashMap.newKeySet();
    private final ExecutorService workers = Executors.newCachedThreadPool();
    private final Semaphore slots = new Semaphore(128);
    private final AtomicLong flows = new AtomicLong();
    private final AtomicLong tcpConnections = new AtomicLong();
    private final AtomicLong tcpUp = new AtomicLong(), tcpDown = new AtomicLong();
    private final AtomicLong udpUp = new AtomicLong(), udpDown = new AtomicLong();
    private final AtomicLong failures = new AtomicLong();
    private final AtomicLong mirrorFailures = new AtomicLong();
    private final Map<Integer, AtomicLong> ports = new ConcurrentHashMap<>();
    private volatile String lastError = "", lastRemote = "";
    private volatile boolean closed;
    private volatile boolean mirrorFailed;

    public LocalSocks(Protector protector, Mirror mirror, String password) throws IOException {
        this.protector = protector; this.mirror = mirror; this.password = password;
        listener = new ServerSocket();
        listener.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0), 64);
        workers.execute(this::accept);
    }
    public int port() { return listener.getLocalPort(); }
    public boolean isRunning() { return !closed && !listener.isClosed(); }
    public Map<String, Object> diagnostics() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("tcp_connections", tcpConnections.get());
        result.put("tcp_bytes_up", tcpUp.get());
        result.put("tcp_bytes_down", tcpDown.get());
        result.put("udp_packets_up", udpUp.get());
        result.put("udp_packets_down", udpDown.get());
        result.put("transport_errors", failures.get());
        result.put("mirror_errors", mirrorFailures.get());
        result.put("last_transport_error", lastError);
        result.put("last_tcp_remote", lastRemote);
        Map<String, Long> portCounts = new TreeMap<>();
        ports.forEach((port, count) -> portCounts.put(String.valueOf(port), count.get()));
        result.put("tcp_port_counts", portCounts);
        return result;
    }
    private void recordFailure(IOException error) {
        if (!closed) {
            failures.incrementAndGet();
            lastError = error.getClass().getSimpleName() + ": " + error.getMessage();
        }
    }
    private void accept() {
        while (!closed) {
            try {
                Socket client = listener.accept();
                if (!slots.tryAcquire()) { client.close(); continue; }
                sockets.add(client);
                workers.execute(() -> { try { session(client); } catch (IOException error) { recordFailure(error); }
                    finally { closeSocket(client); slots.release(); } });
            } catch (IOException | RejectedExecutionException e) { if (!closed) close(); }
        }
    }
    private void session(Socket client) throws IOException {
        client.setSoTimeout(15000);
        DataInputStream in = new DataInputStream(client.getInputStream());
        OutputStream out = client.getOutputStream();
        if (in.readUnsignedByte() != 5) return;
        int count = in.readUnsignedByte(); boolean auth = false;
        for (int i = 0; i < count; i++) auth |= in.readUnsignedByte() == 2;
        out.write(new byte[]{5, (byte)(auth ? 2 : 255)}); out.flush();
        if (!auth || in.readUnsignedByte() != 1) return;
        byte[] userBytes = new byte[in.readUnsignedByte()]; in.readFully(userBytes);
        byte[] passBytes = new byte[in.readUnsignedByte()]; in.readFully(passBytes);
        String username = new String(userBytes, StandardCharsets.UTF_8);
        String supplied = new String(passBytes, StandardCharsets.UTF_8);
        boolean ok = "roco".equals(username) && password.equals(supplied);
        out.write(new byte[]{1, (byte)(ok ? 0 : 1)}); out.flush(); if (!ok) return;
        if (in.readUnsignedByte() != 5) return;
        int command = in.readUnsignedByte();
        if (in.readUnsignedByte() != 0) return;
        InetSocketAddress remote = address(in);
        if (command == 1) tcp(client, remote, in, out);
        else if (command == 3) udp(client, out);
        else reply(out, 7, InetAddress.getLoopbackAddress(), 0);
    }
    private void tcp(Socket client, InetSocketAddress remote, InputStream in, OutputStream out) throws IOException {
        Socket upstream = new Socket(); sockets.add(upstream);
        String id = "tcp-" + flows.incrementAndGet();
        try {
            upstream.bind(new InetSocketAddress(0)); // Android creates the fd lazily; protect needs a real fd.
            if (!protector.tcp(upstream)) throw new IOException("VPN protect failed");
            try { upstream.connect(remote, 15000); }
            catch (IOException e) { recordFailure(e); reply(out, 5, InetAddress.getLoopbackAddress(), 0); return; }
            tcpConnections.incrementAndGet();
            lastRemote = remote.getAddress().getHostAddress() + ":" + remote.getPort();
            if (ports.containsKey(remote.getPort()) || ports.size() < 64)
                ports.computeIfAbsent(remote.getPort(), key -> new AtomicLong()).incrementAndGet();
            client.setSoTimeout(0); upstream.setTcpNoDelay(true); client.setTcpNoDelay(true);
            reply(out, 0, upstream.getLocalAddress(), upstream.getLocalPort());
            Future<?> receive = workers.submit(() -> {
                try { copy(upstream.getInputStream(), out, id, remote, "s2c"); client.shutdownOutput(); }
                catch (IOException e) { recordFailure(e); closeSocket(client); }
            });
            try { copy(in, upstream.getOutputStream(), id, remote, "c2s"); upstream.shutdownOutput(); }
            catch (IOException e) { recordFailure(e); closeSocket(upstream); }
            try { receive.get(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            catch (ExecutionException ignored) { }
        } finally {
            closeSocket(upstream);
            if (!mirrorFailed) try { mirror.closed(id); } catch (RuntimeException error) { mirrorFailure(error); }
        }
    }
    private synchronized void mirrorFailure(RuntimeException error) {
        if (mirrorFailed) return;
        mirrorFailed = true;
        mirrorFailures.incrementAndGet();
        try { mirror.failed("镜像分析暂停: " + error.getClass().getSimpleName() + ": " + error.getMessage()); }
        catch (RuntimeException ignored) { }
    }
    private void copy(InputStream in, OutputStream out, String id, InetSocketAddress remote, String dir) throws IOException {
        byte[] buffer = new byte[32768]; int n;
        while ((n = in.read(buffer)) != -1) {
            if ("c2s".equals(dir)) tcpUp.addAndGet(n); else tcpDown.addAndGet(n);
            // Queue each observed chunk before forwarding can trigger a response in the other direction.
            if (!mirrorFailed) try {
                if (mirror.interested(id))
                    mirror.data(id, remote.getAddress().getHostAddress(), remote.getPort(), dir, Arrays.copyOf(buffer, n));
            } catch (RuntimeException error) { mirrorFailure(error); }
            out.write(buffer, 0, n);
        }
    }
    private void udp(Socket client, OutputStream out) throws IOException {
        DatagramSocket local = new DatagramSocket(new InetSocketAddress("127.0.0.1", 0)); sockets.add(local);
        Map<InetSocketAddress, DatagramSocket> remotes = new ConcurrentHashMap<>();
        reply(out, 0, InetAddress.getByName("127.0.0.1"), local.getLocalPort());
        client.setSoTimeout(0);
        workers.execute(() -> {
            SocketAddress peer = null;
            try {
                byte[] buffer = new byte[65535];
                while (!local.isClosed()) {
                    DatagramPacket packet = new DatagramPacket(buffer, buffer.length); local.receive(packet);
                    if (!packet.getAddress().isLoopbackAddress()) continue;
                    if (peer == null) peer = packet.getSocketAddress();
                    if (!peer.equals(packet.getSocketAddress())) continue;
                    DataInputStream input = new DataInputStream(new ByteArrayInputStream(buffer, 0, packet.getLength()));
                    InetSocketAddress destination;
                    try {
                        if (input.readUnsignedShort() != 0 || input.readUnsignedByte() != 0) continue;
                        destination = address(input);
                    } catch (IOException invalidPacket) { recordFailure(invalidPacket); continue; }
                    byte[] payload = new byte[input.available()]; input.readFully(payload);
                    DatagramSocket upstream = remotes.get(destination);
                    if (upstream == null) {
                        if (remotes.size() >= 64) continue;
                        upstream = new DatagramSocket(null); sockets.add(upstream);
                        upstream.bind(new InetSocketAddress(0));
                        if (!protector.udp(upstream)) { closeSocket(upstream); throw new IOException("VPN protect failed"); }
                        upstream.connect(destination);
                        remotes.put(destination, upstream);
                        DatagramSocket socket = upstream; SocketAddress target = peer;
                        workers.execute(() -> {
                            try {
                                byte[] replyBuffer = new byte[65507];
                                while (!socket.isClosed()) {
                                    DatagramPacket response = new DatagramPacket(replyBuffer, replyBuffer.length); socket.receive(response);
                                    ByteArrayOutputStream encoded = new ByteArrayOutputStream(); encoded.write(new byte[]{0,0,0});
                                    writeAddress(encoded, destination.getAddress(), destination.getPort());
                                    encoded.write(replyBuffer, 0, response.getLength()); byte[] bytes = encoded.toByteArray();
                                    local.send(new DatagramPacket(bytes, bytes.length, target));
                                    udpDown.incrementAndGet();
                                }
                            } catch (IOException ignored) { } finally { remotes.remove(destination, socket); closeSocket(socket); }
                        });
                    }
                    upstream.send(new DatagramPacket(payload, payload.length));
                    udpUp.incrementAndGet();
                }
            } catch (IOException | RejectedExecutionException ignored) { } finally { closeSocket(client); }
        });
        try { while (client.getInputStream().read() != -1) { } }
        finally { closeSocket(local); remotes.values().forEach(this::closeSocket); }
    }
    private static InetSocketAddress address(DataInputStream in) throws IOException {
        int type = in.readUnsignedByte(); InetAddress host;
        if (type == 1 || type == 4) { byte[] bytes = new byte[type == 1 ? 4 : 16]; in.readFully(bytes); host = InetAddress.getByAddress(bytes); }
        else if (type == 3) { int len = in.readUnsignedByte(); byte[] name = new byte[len]; in.readFully(name); host = InetAddress.getByName(new String(name, StandardCharsets.US_ASCII)); }
        else throw new IOException("Invalid SOCKS address");
        return new InetSocketAddress(host, in.readUnsignedShort());
    }
    private static void writeAddress(OutputStream out, InetAddress host, int port) throws IOException {
        byte[] address = host.getAddress(); out.write(address.length == 4 ? 1 : 4); out.write(address); out.write(port >>> 8); out.write(port & 255);
    }
    private static void reply(OutputStream out, int status, InetAddress host, int port) throws IOException {
        out.write(new byte[]{5, (byte)status, 0}); writeAddress(out, host, port); out.flush();
    }
    private void closeSocket(Closeable socket) { sockets.remove(socket); try { socket.close(); } catch (IOException ignored) { } }
    @Override public void close() { closed = true; try { listener.close(); } catch (IOException ignored) { } sockets.forEach(this::closeSocket); workers.shutdownNow(); }
}
