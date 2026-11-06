# Pinned Android transport

The application uses the upstream MIT-licensed `heiher/hev-socks5-tunnel` 2.19.3 Android AAR, with its JNI binding unchanged.

- Source: https://github.com/heiher/hev-socks5-tunnel/tree/2.19.3
- Source commit: `c5584feca8f6df70ee53eb2879e034b849a3d15a`
- Artifact: https://github.com/heiher/hev-socks5-tunnel/releases/download/2.19.3/hev-socks5-tunnel.aar
- SHA-256: `ab6c581e6157680cfe5687ee7bbdcf95405c006c2db3701879ec44b9e5f83836`
- Unmodified upstream source including pinned submodules: `mobile/vendor/hev-socks5-tunnel`.
- The upstream LICENSE and bundled third-party notices must accompany redistribution.

Build pins: Gradle 8.11.1, Android Gradle Plugin 8.9.2, Chaquopy 17.2.0, Python 3.13. Official Chaquopy compatibility and supported packages: https://chaquo.com/chaquopy/doc/current/android.html . Android ABI targets are arm64-v8a and x86_64; minimum Android API is 29 (upstream native library requirement).

The internal debug APK is **not approved for public distribution**: Python bytecode is not a secrecy boundary. Signing keys belong outside this repository and all delivery assets. The generated encrypted resource pack must be staged by the mobile resource builder before building.

The SOCKS server binds only to 127.0.0.1 on an ephemeral port and requires a per-session random credential. Every outbound TCP and UDP socket is protected from VPN recursion. Only the selected app is routed. TCP streams on all destination ports are observed from their first byte and copied in each direction to the mobile Python protocol detector. Each chunk enters the mirror queue before forwarding can trigger the next response. The Python side selects recognized game protocol streams for the shared decoder. Queue errors and native process failure tear down the VPN and produce a visible diagnostic.

Validation still required on a real phone: game protocol recognition, encrypted battle payload calibration, OEM background restrictions, and overlay readability during play. A running VPN and loopback transfer tests do not establish any of those results.

The pure-Python `msgpack` 1.1.2 wheel in `app/libs` is built from upstream using `MSGPACK_PUREPYTHON=1 python -m pip wheel --no-deps --no-binary=msgpack msgpack==1.1.2`. SHA-256: `abb9d1a6928c6d68c143114c203dd6f683c31dbdc69e7b09e6d95920f57281c4`. This uses the upstream fallback implementation because no matching Android native wheel is published in Chaquopy's package index. The APK bundles the upstream native transport licenses under `assets/licenses`.

For device integration tests, `VpnForwardingTest` uses the separately installed test APK's UID, a real `VpnService`, and emulator-host TCP/UDP fixtures on ports 18080/18081. It requires prior VPN consent and skips when consent is absent. `RuntimeTest` loads the packaged native library, encrypted resources, Python runtime, and shared HTTP/HUD. Neither suite injects a fake game victory or claims battle calibration. Fixture processes and private compiler input copies must be removed after validation.
