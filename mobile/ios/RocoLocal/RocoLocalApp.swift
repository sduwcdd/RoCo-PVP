import SwiftUI
import WebKit

@main
struct RocoLocalApp: App {
    var body: some Scene { WindowGroup { LocalPanel() } }
}

struct LocalPanel: View {
    @StateObject private var engine = LocalEngine()
    @StateObject private var preview = HUDPreview()

    var body: some View {
        VStack(spacing: 10) {
            HStack {
                Text("洛克 · 本机助手").font(.headline)
                Spacer()
                Button("画中画") { preview.start() }.disabled(!preview.possible)
                    .accessibilityHint("只读状态视频；完整操作请在助手内进行")
            }
            Text(engine.message).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
            HStack {
                Button(engine.busy ? "启动中…" : "启动本机引擎") { engine.start() }
                    .disabled(engine.busy || engine.baseURL != nil)
                Button("VPN 尚未就绪", action: {}).disabled(true)
            }
            Text("当前版本未接通 iOS 游戏流量。画中画仅显示收到的真实快照，后台可能冻结，以更新时间为准。")
                .font(.caption).foregroundStyle(.secondary)
            if let url = engine.baseURL {
                LocalWebView(url: url.appendingPathComponent("mobile"), onPiP: { preview.start() })
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "iphone.and.arrow.forward").font(.largeTitle)
                    Text("完整面板在本机运行")
                    Text("内置相同 Python 引擎及规则资源；启动后不需要电脑或云端服务。")
                        .font(.caption).multilineTextAlignment(.center)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            PreviewSurface(preview: preview).frame(height: 108)
            if !preview.failure.isEmpty { Text(preview.failure).font(.caption).foregroundStyle(.red) }
        }
        .padding()
        .task { preview.begin(); engine.onSnapshot = { preview.update($0) }; engine.start() }
    }
}

@MainActor
final class LocalEngine: ObservableObject {
    @Published var baseURL: URL?
    @Published var busy = false
    @Published var message = "尚未启动"
    var onSnapshot: (([String: Any]?) -> Void)?
    private let queue = DispatchQueue(label: "cn.roco.engine")
    private var timer: Timer?
    private var polling = false
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 3
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpShouldSetCookies = false
        return URLSession(configuration: configuration)
    }()

    func start() {
        guard !busy, baseURL == nil else { return }
        busy = true
        message = "正在验证并载入内置规则…"
        queue.async { [weak self] in
            do {
                let manager = FileManager.default
                let documents = try manager.url(for: .applicationSupportDirectory, in: .userDomainMask,
                    appropriateFor: nil, create: true)
                let root = documents.appendingPathComponent("RocoLocal", isDirectory: true)
                try manager.createDirectory(at: root, withIntermediateDirectories: true,
                    attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
                guard let archive = Bundle.main.url(forResource: "resources", withExtension: "rpk") else {
                    throw NSError(domain: "RocoResources", code: 1, userInfo: [NSLocalizedDescriptionKey: "缺少内置资源；先执行 prepare-runtime.py"])
                }
                try Data(contentsOf: archive).write(to: root.appendingPathComponent("resources.rpk"), options: .atomic)
                let port = try EngineBridge.start(root: root.path)
                guard port > 0, let url = URL(string: "http://127.0.0.1:\(port)/") else {
                    throw NSError(domain: "RocoEngine", code: 1, userInfo: [NSLocalizedDescriptionKey: "本机引擎没有就绪"])
                }
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.busy = false
                    self.baseURL = url
                    self.message = "本机引擎已启动 · 未连接 iOS 游戏流量"
                    self.timer?.invalidate()
                    self.timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.poll() }
                    self.poll()
                }
            } catch {
                DispatchQueue.main.async {
                    self?.busy = false
                    self?.message = "启动失败：\(error.localizedDescription)"
                    self?.onSnapshot?(nil)
                }
            }
        }
    }

    private func poll() {
        guard let baseURL, !polling else { return }
        polling = true
        session.dataTask(with: baseURL.appendingPathComponent("api/hud/snapshot")) { [weak self] data, response, error in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200 && error == nil
            let snapshot = ok ? data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } : nil
            DispatchQueue.main.async {
                guard let self else { return }
                self.polling = false
                self.onSnapshot?(snapshot)
                if !ok { self.message = "本机接口暂不可达 · 快照已标记失效" }
                else { self.message = "本机引擎已启动 · 未连接 iOS 游戏流量" }
            }
        }.resume()
    }
}

struct LocalWebView: UIViewRepresentable {
    let url: URL
    let onPiP: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(origin: url, onPiP: onPiP) }
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.add(context.coordinator, name: "rocoNative")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        let origin: URL
        let onPiP: () -> Void
        init(origin: URL, onPiP: @escaping () -> Void) { self.origin = origin; self.onPiP = onPiP }
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
                url.scheme == "http", url.host == "127.0.0.1", url.port == origin.port,
                let body = message.body as? [String: Any], body["action"] as? String == "pip" else { return }
            onPiP()
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let target = navigationAction.request.url,
                target.scheme == "http", target.host == "127.0.0.1", target.port == origin.port else {
                decisionHandler(.cancel); return
            }
            decisionHandler(.allow)
        }
    }
}
