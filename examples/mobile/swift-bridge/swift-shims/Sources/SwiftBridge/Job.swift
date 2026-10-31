import Foundation
import UserNotifications

/// Runs Swift `async` work that reports progress and can be cancelled, and
/// keeps the outcome until Python reads it.
///
/// A completion handler can do neither, so for such work a method starts it
/// and returns a Job right away. Python checks `isFinished` and `progress`
/// from Kivy's Clock, calls `cancel()` when the user asks, then reads
/// `result` or `errorMessage`. The properties are behind a lock because the
/// work runs on another thread.
@objc(SBJob)
public final class Job: NSObject {
    private let lock = NSLock()
    private var _state = "running"
    private var _progress = 0.0
    private var _result: Any?
    private var _errorMessage: String?
    private var task: Task<Void, Never>?

    /// "running", "done", "failed" or "cancelled".
    @objc public var state: String { lock.withLock { _state } }
    @objc public var isFinished: Bool { lock.withLock { _state != "running" } }
    /// From 0.0 to 1.0, for work that reports it.
    @objc public var progress: Double { lock.withLock { _progress } }
    /// The work's return value, as an Objective-C object, once `state` is "done".
    @objc public var result: Any? { lock.withLock { _result } }
    /// The error's description, once `state` is "failed".
    @objc public var errorMessage: String? { lock.withLock { _errorMessage } }

    /// The task holds the Job until the work ends, so the result survives
    /// even if Python drops its reference early.
    init(_ work: @escaping (Job) async throws -> Any?) {
        super.init()
        task = Task.detached { [self] in
            do {
                let value = try await work(self)
                finish("done", result: value, error: nil)
            } catch is CancellationError {
                finish("cancelled", result: nil, error: nil)
            } catch {
                finish("failed", result: nil, error: error.localizedDescription)
            }
        }
    }

    /// Asks the work to stop. It stops at its next cancellation check.
    @objc public func cancel() {
        task?.cancel()
    }

    func report(progress: Double) {
        lock.withLock { _progress = progress }
    }

    private func finish(_ state: String, result: Any?, error: String?) {
        lock.withLock {
            _state = state
            _result = result
            _errorMessage = error
            if state == "done" { _progress = 1 }
        }
    }
}

/// Async work the app starts from Python.
@objc(SBWork)
public final class Work: NSObject {
    /// Long-running work that reports progress and can be cancelled, so it
    /// returns a Job for Python to poll.
    @objc(countPrimesBelow:)
    public static func countPrimes(below limit: Int) -> Job {
        Job { job in
            var found = 0
            for n in 2..<max(limit, 2) {
                if n % 10_000 == 0 {
                    try Task.checkCancellation()
                    job.report(progress: Double(n) / Double(limit))
                }
                if isPrime(n) { found += 1 }
            }
            return found
        }
    }

    // Objective-C sees each `async` method below as one whose last argument is
    // a completion handler. Python passes a function, which Swift calls on one
    // of its own threads when the work ends.

    /// An Apple async API, wrapped. The handler receives the settings.
    @objc(notificationSettingsWithCompletionHandler:)
    public static func notificationSettings() async -> [String: Any] {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return [
            "authorizationStatus": settings.authorizationStatus.rawValue,
            "alertsEnabled": settings.alertSetting == .enabled,
        ]
    }

    /// A throwing `async` method. Its completion handler takes the result and
    /// an error, and exactly one of them is nil.
    @objc(failingWorkWithCompletionHandler:)
    public static func failingWork() async throws -> String {
        try await Task.sleep(nanoseconds: 200_000_000)
        throw NSError(domain: "SBWork", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "the work failed on purpose"])
    }

    private static func isPrime(_ n: Int) -> Bool {
        if n < 4 { return n > 1 }
        if n % 2 == 0 { return false }
        var d = 3
        while d * d <= n {
            if n % d == 0 { return false }
            d += 2
        }
        return true
    }
}
