import Foundation

/// What a Metronome tells its delegate. Python implements it with a
/// Rubicon-ObjC class declared with
/// `protocols=[ObjCProtocol("SBMetronomeDelegate")]`, which finds a Swift
/// @objc protocol by name at runtime.
@objc(SBMetronomeDelegate)
public protocol MetronomeDelegate: NSObjectProtocol {
    @objc(metronome:didTick:)
    func metronome(_ metronome: Metronome, didTick count: Int)

    /// Optional: a delegate that leaves it out is never sent it.
    @objc(metronome:didStopWithSummary:)
    optional func metronome(_ metronome: Metronome, didStopWithSummary summary: [String: Any])

    /// Optional: return false to stop after this tick. Without it, the
    /// metronome runs until `stop()`.
    @objc(metronome:shouldContinueAfter:)
    optional func metronome(_ metronome: Metronome, shouldContinueAfter count: Int) -> Bool
}

/// Calls its delegate on a timer, the way SDK classes call theirs.
@objc(SBMetronome)
public final class Metronome: NSObject {
    /// Weak, like UIKit delegates: the app must keep a reference to it.
    @objc public weak var delegate: MetronomeDelegate?
    /// Seconds between ticks.
    @objc public var interval = 0.5
    @objc public private(set) var ticks = 0
    @objc public var isRunning: Bool { timer != nil }
    private var timer: Timer?

    /// Ticks on the main thread, where Kivy runs, so the delegate can touch
    /// widgets. Call it from the main thread: Kivy's own thread on iOS.
    ///
    /// An SDK that calls back on another thread would run the Python delegate
    /// on that thread. Hop to the main queue first, as `tick()` would with
    /// `DispatchQueue.main.async { ... }`.
    @objc public func start() {
        timer?.invalidate()
        ticks = 0
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            self?.tick()
        }
    }

    @objc public func stop() {
        guard let timer else { return }
        timer.invalidate()
        self.timer = nil
        delegate?.metronome?(self, didStopWithSummary: [
            "ticks": ticks,
            "interval": interval,
        ])
    }

    private func tick() {
        ticks += 1
        delegate?.metronome(self, didTick: ticks)
        if delegate?.metronome?(self, shouldContinueAfter: ticks) == false {
            stop()
        }
    }
}
