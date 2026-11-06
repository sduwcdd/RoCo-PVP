import NetworkExtension

final class PacketTunnelProvider: NEPacketTunnelProvider {
    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        // Do not install routes until a public-API packetFlow transport is complete.
        completionHandler(NSError(domain: "RocoTransportUnavailable", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "iOS 本机转发器尚未接通和真机验证；未设置 VPN 路由。请先使用助手内完整面板。"
        ]))
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        completionHandler()
    }

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        let reply = "{\"running\":false,\"transport_ready\":false,\"error\":\"iOS packetFlow transport unavailable\"}"
        completionHandler?(reply.data(using: .utf8))
    }
}
