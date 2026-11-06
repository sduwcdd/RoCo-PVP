import SwiftUI
import AVKit
import CoreVideo
import CoreMedia
import UIKit

@MainActor
final class HUDPreview: NSObject, ObservableObject, AVPictureInPictureSampleBufferPlaybackDelegate, AVPictureInPictureControllerDelegate {
    @Published var possible = false
    @Published var failure = ""
    let displayLayer = AVSampleBufferDisplayLayer()
    private var controller: AVPictureInPictureController?
    private var observation: NSKeyValueObservation?
    private var timer: Timer?
    private var snapshot: [String: Any]?

    func begin() {
        guard timer == nil else { return }
        displayLayer.videoGravity = .resizeAspect
        if AVPictureInPictureController.isPictureInPictureSupported() {
            let source = AVPictureInPictureController.ContentSource(sampleBufferDisplayLayer: displayLayer, playbackDelegate: self)
            controller = AVPictureInPictureController(contentSource: source)
            controller?.delegate = self
            controller?.canStartPictureInPictureAutomaticallyFromInline = false
            observation = controller?.observe(\.isPictureInPicturePossible, options: [.initial, .new]) { [weak self] controller, _ in
                DispatchQueue.main.async { self?.possible = controller.isPictureInPicturePossible }
            }
        } else { failure = "该设备不支持画中画" }
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.render() }
        render()
    }

    func update(_ value: [String: Any]?) { snapshot = value; render() }
    func start() {
        guard let controller, controller.isPictureInPicturePossible else { failure = "画中画尚不可用"; return }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
            try AVAudioSession.sharedInstance().setActive(true)
            controller.startPictureInPicture()
        } catch { failure = error.localizedDescription }
    }

    private func lines() -> [String] {
        guard let snapshot else { return ["洛克 · 本机状态", "接口不可达 / 尚未收到数据", "未接通 iOS 游戏流量", "后台可能冻结 · 以更新时间为准"] }
        guard let payload = snapshot["payload"] as? [String: Any],
            let runtime = payload["runtime"] as? [String: Any] else {
            let state = snapshot["state"] as? [String: Any]
            return ["洛克 · 本机状态", "没有真实战斗快照", state?["hint"] as? String ?? "等待本机协议数据", "未接通 iOS 游戏流量"]
        }
        let timestamp = (snapshot["at"] as? NSNumber)?.doubleValue ?? 0
        let age = timestamp > 0 ? max(0, Date().timeIntervalSince1970 - timestamp) : .infinity
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        let time = timestamp > 0 ? formatter.string(from: Date(timeIntervalSince1970: timestamp)) : "未知"
        let round = (runtime["round"] as? NSNumber)?.stringValue ?? "?"
        let active = runtime["active"] as? [String: [String: Any]] ?? [:]
        let hp = runtime["hp"] as? [String: [String: Any]] ?? [:]
        func side(_ key: String, _ label: String, _ teamKey: String) -> String {
            let team = runtime[teamKey] as? [[String: Any]] ?? []
            let index = (active[key]?["rosterIndex"] as? NSNumber)?.intValue ?? -1
            let pet = team.indices.contains(index) ? team[index] : [:]
            let name = pet["name"] as? String ?? pet["petName"] as? String ?? "未知宠物"
            let value = hp[key] ?? [:]
            let current = value["hpAfter"].map { String(describing: $0) } ?? "?"
            let percent = value["percent"].map { String(describing: $0) } ?? "?"
            return "\(label) \(name)  HP \(current) (\(percent)%)"
        }
        return ["回合 \(round)  ·  \(age > 5 ? "快照陈旧" : "快照更新")  \(time)",
                side("my", "我方", "myTeam"), side("enemy", "对方", "enemyTeam"),
                "只读预览 · 后台可能冻结 · 完整面板见助手"]
    }

    private func render() {
        let width = 800, height = 300
        var buffer: CVPixelBuffer?
        let attributes: [CFString: Any] = [kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true, kCVPixelBufferIOSurfacePropertiesKey: [:]]
        guard CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA,
            attributes as CFDictionary, &buffer) == kCVReturnSuccess, let buffer else { return }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let context = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: width, height: height,
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer), space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue) else { return }
        context.setFillColor(UIColor(red: 0.04, green: 0.09, blue: 0.14, alpha: 1).cgColor)
        context.fill(CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
        context.translateBy(x: 0, y: CGFloat(height)); context.scaleBy(x: 1, y: -1)
        UIGraphicsPushContext(context)
        for (index, line) in lines().enumerated() {
            let color: UIColor = index == 0 ? .systemTeal : .white
            (line as NSString).draw(in: CGRect(x: 24, y: CGFloat(22 + index * 66), width: CGFloat(width - 48), height: 60),
                withAttributes: [.font: UIFont.systemFont(ofSize: index == 3 ? 23 : 29, weight: .medium), .foregroundColor: color])
        }
        UIGraphicsPopContext()
        var description: CMVideoFormatDescription?
        guard CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: buffer,
            formatDescriptionOut: &description) == noErr, let description else { return }
        var timing = CMSampleTimingInfo(duration: CMTime(value: 1, timescale: 1),
            presentationTimeStamp: CMTime(seconds: CACurrentMediaTime(), preferredTimescale: 600), decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: buffer,
            formatDescription: description, sampleTiming: &timing, sampleBufferOut: &sample) == noErr, let sample else { return }
        if displayLayer.status == .failed { displayLayer.flush() }
        if displayLayer.isReadyForMoreMediaData { displayLayer.enqueue(sample) }
    }

    func pictureInPictureController(_ controller: AVPictureInPictureController, setPlaying playing: Bool) {}
    func pictureInPictureControllerTimeRangeForPlayback(_ controller: AVPictureInPictureController) -> CMTimeRange {
        CMTimeRange(start: .negativeInfinity, duration: .positiveInfinity)
    }
    func pictureInPictureControllerIsPlaybackPaused(_ controller: AVPictureInPictureController) -> Bool { false }
    func pictureInPictureController(_ controller: AVPictureInPictureController, didTransitionToRenderSize newRenderSize: CMVideoDimensions) {}
    func pictureInPictureController(_ controller: AVPictureInPictureController, skipByInterval skipInterval: CMTime,
                                   completionHandler: @escaping () -> Void) { completionHandler() }
    func pictureInPictureController(_ controller: AVPictureInPictureController, failedToStartPictureInPictureWithError error: Error) {
        failure = error.localizedDescription
    }
    func pictureInPictureController(_ controller: AVPictureInPictureController, restoreUserInterfaceForPictureInPictureStopWithCompletionHandler completionHandler: @escaping (Bool) -> Void) { completionHandler(true) }
}

struct PreviewSurface: UIViewRepresentable {
    let preview: HUDPreview
    func makeUIView(context: Context) -> Surface {
        let view = Surface()
        view.layer.addSublayer(preview.displayLayer)
        view.accessibilityLabel = "真实战斗状态的只读视频预览"
        view.isAccessibilityElement = true
        return view
    }
    func updateUIView(_ uiView: Surface, context: Context) { preview.displayLayer.frame = uiView.bounds }
    final class Surface: UIView {
        override func layoutSubviews() { super.layoutSubviews(); layer.sublayers?.forEach { $0.frame = bounds } }
    }
}
