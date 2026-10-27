import Foundation

/// What a Metronome tells its delegate. Python implements it with pyobjus'
/// `@protocol("SBMetronomeDelegate")`. pyobjus finds a Swift @objc protocol
/// by name at runtime, so it needs no entry in pyobjus' protocol table.
///
/// The methods return nothing. pyobjus 1.2.5 drops a Python delegate's return
/// value (Swift reads zero, false or nil), so anything the Metronome needs to
/// ask the app, such as when to stop, is a property the app sets instead.
@objc(SBMetronomeDelegate)
public protocol MetronomeDelegate: NSObjectProtocol {
    @objc(metronome:didTick:)
    func metronome(_ metronome: Metronome, didTick count: Int)

    /// Optional: a delegate that leaves it out is never sent it.
    @objc(metronome:didStopWithSummary:)
    optional func metronome(_ metronome: Metronome, didStopWithSummary summary: [String: Any])
}

/// Calls its delegate on a timer, the way SDK classes call theirs.
@objc(SBMetronome)
public final class Metronome: NSObject {
    /// Weak, like UIKit delegates. pyobjus keeps the Python delegate alive.
    @objc public weak var delegate: MetronomeDelegate?
    /// Seconds between ticks.
    @objc public var interval = 0.5
    /// Stop after this many ticks; 0 runs until `stop()`.
    @objc public var maxTicks = 0
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
            "reachedLimit": maxTicks > 0 && ticks >= maxTicks,
        ])
    }

    private func tick() {
        ticks += 1
        delegate?.metronome(self, didTick: ticks)
        if maxTicks > 0 && ticks >= maxTicks {
            stop()
        }
    }
}
