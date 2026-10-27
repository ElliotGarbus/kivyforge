import Foundation

/// An object with state: initialisers, properties, collections in and out,
/// and a throwing method. Python creates it with
/// `autoclass("SBNotebook").alloc().initWithTitle_("...")`.
///
/// Every signature uses types Objective-C can represent: String, Int, Double,
/// Bool, arrays and dictionaries of those, and NSObject subclasses. A Swift
/// struct, enum with associated values, generic or tuple cannot be @objc, so
/// the shim converts them before they reach Python.
@objc(SBNotebook)
public final class Notebook: NSObject {
    /// A `let` reads from Python as an attribute: `notebook.title`.
    @objc public let title: String
    /// A `var` can also be set: `notebook.author = "..."`.
    @objc public var author = "anonymous"
    /// A read-only array property; Python sees an NSArray.
    @objc public private(set) var notes: [String] = []
    /// Why the last `noteAtIndex:error:` call failed, or nil.
    @objc public private(set) var lastError: String?

    @objc public override convenience init() {
        self.init(title: "Untitled")
    }

    @objc(initWithTitle:)
    public init(title: String) {
        self.title = title
        super.init()
    }

    /// Returns the new number of notes.
    @objc(addNote:)
    public func add(_ text: String) -> Int {
        notes.append(text)
        return notes.count
    }

    /// A flat Python list of strings arrives as `[String]`.
    @objc(addNotes:)
    public func add(contentsOf texts: [String]) -> Int {
        notes.append(contentsOf: texts)
        return notes.count
    }

    /// `[String: Int]` reaches Python as an NSDictionary of NSNumber.
    @objc public func wordCounts() -> [String: Int] {
        var counts: [String: Int] = [:]
        for note in notes {
            for word in note.lowercased().split(whereSeparator: { !$0.isLetter }) {
                counts[String(word), default: 0] += 1
            }
        }
        return counts
    }

    /// Mixed and nested values in one dictionary.
    @objc public func summary() -> [String: Any] {
        let words = notes.reduce(0) { $0 + $1.split(separator: " ").count }
        return [
            "title": title,
            "author": author,
            "count": notes.count,
            "averageWords": notes.isEmpty ? 0.0 : Double(words) / Double(notes.count),
            "isEmpty": notes.isEmpty,
            "latest": Array(notes.suffix(2)),
            "totals": ["words": words, "characters": notes.reduce(0) { $0 + $1.count }],
        ]
    }

    /// Takes a dictionary built in Python with `pyobjus.objc_dict()`.
    /// Returns the keys it received, sorted.
    @objc(applyOptions:)
    public func apply(options: [String: Any]) -> [String] {
        if let author = options["author"] as? String {
            self.author = author
        }
        if let keep = options["keepLast"] as? Int, keep >= 0, keep < notes.count {
            notes.removeFirst(notes.count - keep)
        }
        return options.keys.sorted()
    }

    /// Exported to Objective-C as `-noteAtIndex:error:`. Python calls it as
    /// `noteAtIndex_error_(i, None)` and gets None when it throws. pyobjus
    /// does not return the NSError, so the reason is also kept in `lastError`.
    @objc(noteAtIndex:error:)
    public func note(at index: Int) throws -> String {
        guard notes.indices.contains(index) else {
            let reason = "no note at index \(index); the notebook has \(notes.count)"
            lastError = reason
            throw NSError(domain: "SBNotebook", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: reason])
        }
        lastError = nil
        return notes[index]
    }
}
