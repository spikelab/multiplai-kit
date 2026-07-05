# Swift & SwiftUI Best Practices (2026)

Native iOS and macOS development with Swift 6.2, SwiftUI, Swift Concurrency, and modern Apple frameworks.

**Last updated:** 2026-03-01
**Swift version:** 6.2 (Xcode 26)
**Minimum deployment:** iOS 17+ / macOS 14+ recommended

---

## Table of Contents

1. [Architecture Decision Guide](#1-architecture-decision-guide)
2. [Project Structure](#2-project-structure)
3. [SwiftUI View Patterns](#3-swiftui-view-patterns)
4. [State Management & Observation](#4-state-management--observation)
5. [Swift Concurrency](#5-swift-concurrency)
6. [Data Persistence](#6-data-persistence)
7. [macOS-Specific Patterns](#7-macos-specific-patterns)
8. [Testing](#8-testing)
9. [Code Style & Conventions](#9-code-style--conventions)
10. [Dependencies & Package Management](#10-dependencies--package-management)
11. [Common Anti-Patterns](#11-common-anti-patterns)
12. [Framework Maturity Assessment](#12-framework-maturity-assessment)

---

## 1. Architecture Decision Guide

Apple has **no official architecture recommendation** for SwiftUI. The Swift Forums thread on this topic received no definitive answer from Apple engineers. Their tutorials demonstrate patterns without prescribing them. This means architecture is your choice — informed by project complexity, team size, and your comfort level.

### The Three Viable Paths

| Pattern | Best For | Trade-offs |
|---------|----------|------------|
| **MV (Model-View)** with `@Observable` | Solo devs, small-medium apps, rapid iteration | Simple, aligned with SwiftUI's design; less structure for large teams |
| **MVVM** with `@Observable` ViewModels | Medium-large apps, teams familiar with MVVM | Clear separation; risk of unnecessary ViewModel boilerplate |
| **TCA (Composable Architecture)** | Large apps, complex state, teams wanting strict testability | Excellent testing story; steep learning curve, compile time costs |

### Recommended Default: MV with @Observable

The strongest emerging consensus (Thomas Ricouard, multiple senior engineers) is that SwiftUI apps in 2025-2026 should **not** default to MVVM. SwiftUI views are not objects — they are pure functions of state. The ViewModel layer that was essential in UIKit is often redundant in SwiftUI.

**The pattern:**

```swift
// Model — @Observable class, owns state and logic
@Observable
final class BookStore {
    var books: [Book] = []
    var isLoading = false
    var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    func fetchBooks() async {
        isLoading = true
        defer { isLoading = false }
        do {
            books = try await apiClient.get("/books")
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// View — renders state, triggers actions
struct BookListView: View {
    @State private var store = BookStore()

    var body: some View {
        List(store.books) { book in
            BookRow(book: book)
        }
        .overlay {
            if store.isLoading {
                ProgressView()
            }
        }
        .task {
            await store.fetchBooks()
        }
    }
}
```

**Why this works:**
- `@Observable` tracks property-level changes (not whole-object like `ObservableObject`)
- Views only re-render when properties they actually read change
- No `@Published`, no `objectWillChange`, no Combine boilerplate
- The model is testable without UI (initialize with mock dependencies)

### When to Reach for MVVM

Use a ViewModel layer when:
- A view needs to combine data from multiple independent models
- You need to transform/format model data extensively for display
- Your team is large and needs clear ownership boundaries
- You're bridging UIKit and SwiftUI in the same screen

```swift
@Observable
@MainActor
final class BookDetailViewModel {
    var formattedTitle: String { book.title.uppercased() }
    var reviewSummary: String { "\(book.reviews.count) reviews, avg \(averageRating)" }

    private let book: Book
    private let reviewStore: ReviewStore

    private var averageRating: String {
        let avg = book.reviews.map(\.rating).reduce(0, +) / max(book.reviews.count, 1)
        return String(format: "%.1f", Double(avg))
    }

    init(book: Book, reviewStore: ReviewStore) {
        self.book = book
        self.reviewStore = reviewStore
    }
}
```

### When to Reach for TCA

Consider TCA when:
- Your app has complex, interconnected state (think: financial apps, real-time collaboration)
- You need exhaustive testing of state transitions
- Your team has 4+ iOS engineers and needs architectural consistency
- You want value-type state management (TCA uses structs, not classes)

**Warning:** TCA adds significant complexity. The Arc browser team's public departure from TCA (though they used an early, customized branch) sparked community debate. The compile-time cost is real for large projects. TCA 2 (in preview as of late 2025) aims to reduce this overhead significantly.

**TCA is NOT recommended if:**
- Your app is simple to medium complexity
- You're the only iOS developer
- You want to stay close to Apple's frameworks
- Onboarding speed matters more than architectural rigor

---

## 2. Project Structure

### Feature-Based Organization (Recommended)

```
MyApp/
├── App/
│   ├── MyApp.swift                  # @main App struct
│   ├── AppDelegate.swift            # If needed for push notifications, etc.
│   └── AppConfiguration.swift       # Environment, feature flags
├── Features/
│   ├── Books/
│   │   ├── BookStore.swift          # @Observable model + business logic
│   │   ├── BookListView.swift       # List view
│   │   ├── BookDetailView.swift     # Detail view
│   │   └── Book.swift               # Data model
│   ├── Auth/
│   │   ├── AuthStore.swift
│   │   ├── LoginView.swift
│   │   ├── SignUpView.swift
│   │   └── AuthModels.swift
│   └── Settings/
│       ├── SettingsView.swift
│       └── SettingsStore.swift
├── Core/
│   ├── Network/
│   │   ├── APIClient.swift          # async/await networking
│   │   ├── APIEndpoint.swift        # Endpoint definitions
│   │   └── APIError.swift           # Typed errors
│   ├── Storage/
│   │   ├── PersistenceController.swift
│   │   └── KeychainManager.swift
│   └── Extensions/
│       ├── View+Extensions.swift
│       └── Date+Extensions.swift
├── UI/
│   ├── Components/
│   │   ├── PrimaryButton.swift
│   │   ├── LoadingOverlay.swift
│   │   └── ErrorBanner.swift
│   └── Theme/
│       ├── AppColors.swift
│       ├── AppFonts.swift
│       └── AppSpacing.swift
├── Resources/
│   ├── Assets.xcassets
│   ├── Localizable.xcstrings
│   └── AppIcon.icon               # New in Xcode 26 (Icon Composer format)
└── Tests/
    ├── Features/
    │   ├── BookStoreTests.swift
    │   └── AuthStoreTests.swift
    └── Core/
        └── APIClientTests.swift
```

### File Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Views | `NounView.swift` | `BookListView.swift` |
| Models | `Noun.swift` | `Book.swift` |
| Observable stores | `NounStore.swift` | `BookStore.swift` |
| Extensions | `Type+Context.swift` | `View+Loading.swift` |
| Protocols | `NounProtocol.swift` or `Adjective.swift` | `Fetchable.swift` |

### Swift Package Manager for Modules

For larger apps, extract features into local SPM packages:

```
MyApp/
├── MyApp/                     # Main app target
├── Packages/
│   ├── BookFeature/           # Local package
│   │   ├── Package.swift
│   │   ├── Sources/
│   │   └── Tests/
│   ├── NetworkKit/            # Shared networking
│   └── DesignSystem/          # UI components
└── Package.swift              # Workspace-level
```

**When to modularize:** When build times exceed 30 seconds, or when multiple developers work on independent features. Don't modularize prematurely.

### SwiftPM App Target Pattern (MANDATORY for apps)

**RULE:** When building a SwiftUI app as a SwiftPM package (no .xcodeproj), ALWAYS create both a library target (for testability) and an executable target (for launch). A library-only package cannot run — it will compile and pass tests but never launch. This is the #1 missed step when scaffolding SwiftPM apps.

```swift
// Package.swift — correct pattern for a launchable SwiftPM app
let package = Package(
    name: "MyApp",
    platforms: [.macOS(.v15)],
    products: [
        .library(name: "MyAppLib", targets: ["MyAppLib"]),    // For @testable import
        .executable(name: "MyApp", targets: ["MyApp"]),        // For swift run / Xcode launch
    ],
    targets: [
        // Library: all models, views, ViewModels, services — everything testable
        .target(name: "MyAppLib"),

        // Executable: ONLY the @main App struct, depends on the library
        .executableTarget(
            name: "MyApp",
            dependencies: ["MyAppLib"]
        ),

        // Tests import the library, not the executable
        .testTarget(
            name: "MyAppTests",
            dependencies: ["MyAppLib"]
        ),
    ]
)
```

The executable target's source directory contains a single file:

```swift
// Sources/MyApp/MyApp.swift
import SwiftUI
import MyAppLib

@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}
```

**Why two targets:** `@testable import` doesn't work with executable targets. If you put everything in the executable, your tests can't import it. The library holds all the code; the executable is a thin shell that imports the library and provides `@main`.

**Checklist when scaffolding a SwiftPM app:**
- [ ] Package.swift has `.executable` product (not just `.library`)
- [ ] Executable target has `@main` App struct
- [ ] Library target has all models, views, services
- [ ] Test target depends on library, not executable
- [ ] `swift run` launches the app (verify this before moving on)

---

## 3. SwiftUI View Patterns

### View Composition

Keep views small. Extract subviews when a view exceeds ~50 lines or when a section has its own state/logic.

```swift
struct BookListView: View {
    @State private var store = BookStore()
    @State private var searchText = ""

    var body: some View {
        NavigationStack {
            List {
                ForEach(filteredBooks) { book in
                    NavigationLink(value: book) {
                        BookRow(book: book)
                    }
                }
            }
            .navigationTitle("Library")
            .searchable(text: $searchText)
            .navigationDestination(for: Book.self) { book in
                BookDetailView(book: book)
            }
            .task {
                await store.fetchBooks()
            }
        }
    }

    private var filteredBooks: [Book] {
        if searchText.isEmpty {
            return store.books
        }
        return store.books.filter { $0.title.localizedCaseInsensitiveContains(searchText) }
    }
}
```

### Navigation Patterns

Use `NavigationStack` with typed destinations for type-safe, testable navigation:

```swift
// Define routes as an enum
enum AppRoute: Hashable {
    case bookDetail(Book)
    case authorProfile(Author)
    case settings
}

struct ContentView: View {
    @State private var path = NavigationPath()

    var body: some View {
        NavigationStack(path: $path) {
            BookListView(path: $path)
                .navigationDestination(for: AppRoute.self) { route in
                    switch route {
                    case .bookDetail(let book):
                        BookDetailView(book: book)
                    case .authorProfile(let author):
                        AuthorProfileView(author: author)
                    case .settings:
                        SettingsView()
                    }
                }
        }
    }
}
```

For macOS multi-window apps, use `NavigationSplitView`:

```swift
struct ContentView: View {
    @State private var selectedCategory: Category?
    @State private var selectedBook: Book?

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: $selectedCategory)
        } content: {
            if let category = selectedCategory {
                BookListView(category: category, selection: $selectedBook)
            }
        } detail: {
            if let book = selectedBook {
                BookDetailView(book: book)
            } else {
                ContentUnavailableView("Select a Book", systemImage: "book")
            }
        }
    }
}
```

### Environment & Dependency Injection

Use `@Environment` for cross-cutting concerns. Create custom environment keys for your own dependencies:

```swift
// Define the key
private struct APIClientKey: EnvironmentKey {
    static let defaultValue: APIClient = .shared
}

extension EnvironmentValues {
    var apiClient: APIClient {
        get { self[APIClientKey.self] }
        set { self[APIClientKey.self] = newValue }
    }
}

// Inject at the root
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(\.apiClient, .shared)
        }
    }
}

// Consume in any view
struct BookListView: View {
    @Environment(\.apiClient) private var apiClient

    // ...
}
```

### When to Bridge UIKit/AppKit

SwiftUI-first, but bridge when you need:

| Need | SwiftUI Solution | Bridge When |
|------|-----------------|-------------|
| Large data grids (20k+ items) | `List`, `Table` | Performance degrades beyond 10-20k items |
| Rich text editing | `TextEditor` (iOS 26+) | Need to support < iOS 26 |
| Metal/custom rendering | `Canvas` | Need full `CALayer` control |
| Complex gestures | Gesture API (improved in 2025) | Need pre-iOS 18 gesture velocity |
| Collection view layouts | `LazyVGrid` | Need compositional layout performance |

---

## 4. State Management & Observation

### The Observation Framework (@Observable)

The `@Observable` macro (Swift 5.9+) replaces `ObservableObject`/`@Published`. It tracks property-level access, so views only re-render when the specific properties they read change.

```swift
@Observable
final class UserStore {
    var currentUser: User?
    var isAuthenticated: Bool { currentUser != nil }
    var preferences = UserPreferences()

    func login(email: String, password: String) async throws {
        currentUser = try await AuthService.login(email: email, password: password)
    }

    func logout() {
        currentUser = nil
    }
}
```

### Property Wrappers Cheat Sheet

| Wrapper | Use Case | Notes |
|---------|----------|-------|
| `@State` | View-local value state | Structs, strings, ints. SwiftUI owns the storage. |
| `@Binding` | Child view needs to mutate parent's state | Two-way connection to a `@State` or `@Bindable` property |
| `@Bindable` | Create bindings to `@Observable` properties | Replaces Combine-based bindings |
| `@Environment(Type.self)` | Inject `@Observable` objects | Replaces `@EnvironmentObject` |
| `@Environment(\.key)` | Access environment values | System or custom environment keys |
| `@State` (with `@Observable`) | View-owned observable | `@State private var store = MyStore()` |

### Bindings with @Observable

```swift
@Observable
final class FormStore {
    var name = ""
    var email = ""
    var agreeToTerms = false
}

struct FormView: View {
    @State private var store = FormStore()

    var body: some View {
        Form {
            // @Bindable enables bindings to @Observable properties
            @Bindable var store = store

            TextField("Name", text: $store.name)
            TextField("Email", text: $store.email)
            Toggle("Agree to Terms", isOn: $store.agreeToTerms)
        }
    }
}
```

### The New Observations Type (Swift 6.2)

`Observations` creates an `AsyncSequence` from observable changes — bridging Observation with Swift Concurrency:

```swift
@Observable
final class Store {
    var items: [Item] = []
    var isLoading = false
}

// Stream changes as an async sequence
let store = Store()
let changes = Observations {
    // All properties accessed here are tracked
    State(items: store.items, isLoading: store.isLoading)
}

for await state in changes {
    // Fires whenever items OR isLoading changes
    render(state)
}
```

**Extension pattern for reusable streams:**

```swift
extension Observable {
    func stream<Value: Sendable>(
        of keyPath: KeyPath<Self, Value>
    ) -> some AsyncSequence<Value, Never> {
        Observations { self[keyPath: keyPath] }
    }
}

// Usage
for await items in store.stream(of: \.items) {
    print("Items updated: \(items.count)")
}
```

### Smart Change Detection

The Observation framework automatically skips notifications when an `Equatable` property is set to its current value. You get this for free — no `didSet` guards needed.

### Common Pitfall: Nested Observable Collections

Mutations to items within a collection of `@Observable` objects can cause unexpected full-view reinitializations instead of incremental updates. If you see this, consider a "render key" approach:

```swift
@Observable
final class Item: Identifiable {
    let id = UUID()
    var title: String
    var renderKey = UUID()  // Bump when deep changes occur

    func update(title: String) {
        self.title = title
        renderKey = UUID()
    }
}
```

### Migrating from Combine/ObservableObject

| Old | New |
|-----|-----|
| `class Store: ObservableObject` | `@Observable final class Store` |
| `@Published var x` | `var x` (automatic) |
| `@ObservedObject var store` | `var store` (or `@State` if view-owned) |
| `@EnvironmentObject var store` | `@Environment(Store.self) var store` |
| `@StateObject var store = Store()` | `@State private var store = Store()` |
| Combine publishers | `Observations` async sequences |

---

## 5. Swift Concurrency

### The Swift 6.2 Mental Model

Swift 6.2 introduces **"Approachable Concurrency"** — a fundamentally simpler model:

> "Many apps only need to use concurrency sparingly, and some don't need concurrency at all. Start single-threaded, add concurrency as you need it." — WWDC25

**Key changes:**
1. **MainActor by default** — In app modules, all code is implicitly `@MainActor`
2. **`nonisolated async` runs in caller's context** — No more surprise thread hops
3. **`@concurrent`** — Explicitly opt into background execution

### The Progressive Concurrency Ladder

**Level 0: Synchronous (default in Swift 6.2)**

```swift
// Everything runs on main actor by default
final class ImageModel {
    var imageCache: [URL: Image] = [:]

    // No async needed for simple state management
    func getCachedImage(for url: URL) -> Image? {
        imageCache[url]
    }
}
```

**Level 1: Async for I/O (most apps stop here)**

```swift
final class ImageModel {
    var imageCache: [URL: Image] = [:]

    func fetchImage(url: URL) async throws -> Image {
        if let cached = imageCache[url] { return cached }

        // URLSession handles background I/O internally
        let (data, _) = try await URLSession.shared.data(from: url)
        let image = try decodeImage(data)
        imageCache[url] = image
        return image
    }
}
```

**Level 2: @concurrent for CPU work**

```swift
// Explicitly run on background thread
@concurrent
func decodeImage(_ data: Data) async throws -> Image {
    // Heavy computation happens off main thread
    let cgImage = try ImageDecoder.decode(data)
    return Image(cgImage: cgImage)
}

final class ImageModel {
    func fetchImage(url: URL) async throws -> Image {
        let (data, _) = try await URLSession.shared.data(from: url)
        let image = try await decodeImage(data)  // Background
        return image  // Back on main actor
    }
}
```

**Level 3: Actors for shared mutable state**

```swift
// Only when main actor holds too much state
actor NetworkManager {
    private var connections: [URL: Connection] = [:]

    func connection(for url: URL) -> Connection {
        if let existing = connections[url] { return existing }
        let conn = Connection(url: url)
        connections[url] = conn
        return conn
    }
}
```

### Concurrency Anti-Patterns to Avoid

Based on Matt Massicotte's comprehensive analysis:

**1. Split isolation (partial MainActor)**
```swift
// WRONG — creates non-Sendable type
class MyClass {
    var name: String          // nonisolated
    @MainActor var count: Int // MainActor
}

// RIGHT — isolate the whole type
@MainActor
final class MyClass {
    var name: String
    var count: Int
}
```

**2. MainActor.run instead of proper isolation**
```swift
// WRONG
await MainActor.run { updateUI() }

// RIGHT — annotate the function
@MainActor func updateUI() { ... }
```

**3. Task.detached to escape MainActor**
```swift
// WRONG — loses priority and task-locals
Task.detached { await self.heavyWork() }

// RIGHT — use @concurrent (Swift 6.2) or nonisolated
@concurrent
func heavyWork() async { ... }
```

**4. Actors with no state**
```swift
// WRONG — actors exist to protect state
actor WorkerActor {
    func doWork() async { ... }  // No properties!
}

// RIGHT — use nonisolated async function
nonisolated func doWork() async { ... }
```

**5. Blocking on async work**
```swift
// WRONG — potential deadlock
let semaphore = DispatchSemaphore(value: 0)
Task { await work(); semaphore.signal() }
semaphore.wait()

// RIGHT — use structured concurrency
await work()
```

### Sendable & Value Types

```swift
// Structs with Sendable fields are automatically Sendable
struct BookRequest: Sendable {
    let title: String
    let author: String
    let isbn: String
}

// Classes need explicit handling
@MainActor  // Global actor = automatically Sendable
final class BookStore { ... }

// OR make immutable
final class ImmutableConfig: Sendable {
    let apiKey: String
    let baseURL: URL

    init(apiKey: String, baseURL: URL) {
        self.apiKey = apiKey
        self.baseURL = baseURL
    }
}
```

### Structured Concurrency Patterns

```swift
// Task groups for parallel work
func fetchAllBooks(ids: [String]) async throws -> [Book] {
    try await withThrowingTaskGroup(of: Book.self) { group in
        for id in ids {
            group.addTask {
                try await self.fetchBook(id: id)
            }
        }

        var books: [Book] = []
        for try await book in group {
            books.append(book)
        }
        return books
    }
}

// Cancellation-aware work
func processLargeDataset(_ items: [Item]) async throws {
    for item in items {
        try Task.checkCancellation()  // Bail out if cancelled
        await process(item)
    }
}
```

### Build Settings for Concurrency

| Setting | Value | Effect |
|---------|-------|--------|
| Approachable Concurrency | `Yes` | Enables all Swift 6.2 concurrency improvements |
| Default Actor Isolation | `MainActor` | All code in module is `@MainActor` by default |
| Swift Language Version | `Swift 6` | Enables full data-race safety checking |

---

## 6. Data Persistence

### Decision Matrix

| Framework | Use When | Avoid When |
|-----------|----------|------------|
| **SwiftData** | New app, simple-medium data needs, SwiftUI-first | CloudKit sharing, complex migrations, iOS < 17 |
| **Core Data** | Existing app, CloudKit sharing, complex queries | New app with no legacy (unless you need sharing) |
| **UserDefaults / @AppStorage** | Small key-value settings | Anything over a few KB |
| **GRDB / SQLite** | Need raw SQL control, cross-platform | Want Apple framework integration |
| **Keychain** | Secrets, tokens, passwords | General data storage |

### SwiftData Patterns

SwiftData is **production-ready for most use cases** as of 2025, with critical iOS 18 bugs fixed and backward-compatible improvements to iOS 17. However, it has real limitations.

```swift
import SwiftData

@Model
final class Book {
    var title: String
    var author: String
    var publishDate: Date
    var rating: Int

    // Relationships must be optional
    var reviews: [Review]?

    init(title: String, author: String, publishDate: Date, rating: Int = 0) {
        self.title = title
        self.author = author
        self.publishDate = publishDate
        self.rating = rating
    }
    // Do NOT assign relationship properties in init
}

@Model
final class Review {
    var text: String
    var rating: Int
    var book: Book?

    init(text: String, rating: Int) {
        self.text = text
        self.rating = rating
    }
}
```

**SwiftData in views:**

```swift
struct BookListView: View {
    @Query(sort: \Book.title) private var books: [Book]
    @Environment(\.modelContext) private var context

    var body: some View {
        List(books) { book in
            BookRow(book: book)
        }
    }

    func addBook(_ book: Book) {
        context.insert(book)
    }
}
```

### SwiftData Critical Warnings

1. **Stick to basic types** for properties: `Int`, `Double`, `String`, `Date`, `URL`, `Bool`
2. **Avoid custom `Codable` types** in model properties unless you're certain they won't change (filtering doesn't work on nested Codable properties)
3. **Relationships must be optional** — required for CloudKit sync
4. **Use `@ModelActor`** for background/concurrent operations — only `PersistentIdentifier` and `ModelContainer` are `Sendable`
5. **CloudKit sync is local-first** — not real-time, frequency varies by network/battery
6. **Switching iCloud accounts clears local data** — warn users
7. **CloudKit sharing (shared/public databases)** is NOT supported — use Core Data if you need this

### When to Stick with Core Data

If your app needs any of these, use Core Data (or Core Data + SwiftData hybrid):
- CloudKit sharing (`CKShare`)
- Complex migration logic beyond simple schema changes
- Batch operations at scale (10k+ records)
- Computed/derived properties in the data model
- Advanced NSPredicate usage beyond SwiftData's `#Predicate`

---

## 7. macOS-Specific Patterns

> **Comprehensive guide:** See `swift-macos-best-practices.md` for in-depth macOS coverage including window management, global hotkeys, MenuBarExtra, toolbars, sandboxing, distribution/notarization, XPC services, Liquid Glass, and container development notes.

This section covers the essentials. Load `swift-macos-best-practices.md` when doing macOS-focused work.

### NavigationSplitView (Three-Column Layout)

```swift
struct ContentView: View {
    @State private var selectedCategory: Category?
    @State private var selectedItem: Item?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            List(categories, selection: $selectedCategory) { category in
                Label(category.name, systemImage: category.icon)
            }
            .navigationTitle("Categories")
            .navigationSplitViewColumnWidth(min: 180, ideal: 220, max: 300)
        } content: {
            if let category = selectedCategory {
                List(category.items, selection: $selectedItem) { item in
                    ItemRow(item: item)
                }
            } else {
                ContentUnavailableView("Select a Category", systemImage: "folder")
            }
        } detail: {
            if let item = selectedItem {
                ItemDetailView(item: item)
            } else {
                ContentUnavailableView("Select an Item", systemImage: "doc")
            }
        }
    }
}
```

### Keyboard Shortcuts

```swift
.keyboardShortcut("n", modifiers: .command)        // Cmd+N
.keyboardShortcut(.delete, modifiers: .command)     // Cmd+Delete
```

### Commands (Menu Bar)

```swift
var body: some Scene {
    WindowGroup { ... }
        .commands {
            CommandGroup(after: .newItem) {
                Button("Import Books...") { importBooks() }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
            }
            CommandMenu("Library") {
                Button("Sync") { sync() }
                Divider()
                Button("Export...") { export() }
            }
        }
}
```

### Multiplatform Considerations

When building for both iOS and macOS:

```swift
struct AdaptiveView: View {
    var body: some View {
        #if os(macOS)
        NavigationSplitView { ... }
        #else
        NavigationStack { ... }
        #endif
    }
}
```

Prefer the Multiplatform App template in Xcode. Support at most 3 OS versions back (currently: iOS 17+, macOS 14+).

---

## 8. Testing

### Swift Testing Framework (Preferred for New Tests)

Swift Testing (Xcode 16+) replaces XCTest with a modern, macro-based approach. XCTest is not deprecated — you can mix both in the same target.

```swift
import Testing

@Suite("BookStore Tests")
struct BookStoreTests {

    @Test("fetches books successfully")
    func fetchBooks() async throws {
        let store = BookStore(apiClient: MockAPIClient())
        await store.fetchBooks()

        #expect(store.books.count == 3)
        #expect(store.isLoading == false)
    }

    @Test("handles network errors gracefully")
    func fetchBooksError() async throws {
        let store = BookStore(apiClient: MockAPIClient(shouldFail: true))
        await store.fetchBooks()

        #expect(store.books.isEmpty)
        #expect(store.errorMessage != nil)
    }

    @Test("validates specific error type")
    func specificError() {
        #expect(throws: NetworkError.self) {
            try riskyOperation()
        }
    }
}
```

### Key Swift Testing Patterns

**Parameterized tests eliminate duplication:**

```swift
struct ConversionCase: CustomTestStringConvertible {
    let input: Double
    let rate: Double
    let expected: Double
    var testDescription: String { "\(input) * \(rate) = \(expected)" }
}

let cases = [
    ConversionCase(input: 100, rate: 1.1, expected: 110),
    ConversionCase(input: 50, rate: 0.85, expected: 42.5),
    ConversionCase(input: 0, rate: 1.5, expected: 0),
]

@Test("Currency conversion", arguments: cases)
func conversion(testCase: ConversionCase) {
    let result = convert(testCase.input, rate: testCase.rate)
    #expect(result.isApproximatelyEqual(to: testCase.expected))
}
```

**Nested suites for organization:**

```swift
@Suite("Authentication")
struct AuthTests {
    @Suite("Login")
    struct Login {
        @Test("valid credentials") func validLogin() async throws { ... }
        @Test("invalid password") func invalidPassword() async throws { ... }
    }

    @Suite("Token Management")
    struct TokenManagement {
        @Test("refreshes expired token") func tokenRefresh() async throws { ... }
    }
}
```

**Use `#require` for prerequisites (fails fast):**

```swift
@Test("displays user profile")
func userProfile() throws {
    let config = try #require(loadConfiguration())
    let user = try #require(config.currentUser)

    // Only runs if both prerequisites pass
    #expect(user.displayName == "Test User")
}
```

**Tags for selective test runs:**

```swift
extension Tag {
    @Tag static var unit: Self
    @Tag static var integration: Self
    @Tag static var slow: Self
}

@Test("fast computation", .tags(.unit))
func fastTest() { ... }

@Test("database integration", .tags(.integration, .slow))
func dbTest() async throws { ... }
```

**Time limits prevent CI hangs:**

```swift
@Test("completes within time limit", .timeLimit(.minutes(1)))
func timedTest() async throws { ... }
```

### Migration from XCTest

| XCTest | Swift Testing |
|--------|--------------|
| `class Tests: XCTestCase` | `@Suite struct Tests` |
| `func testSomething()` | `@Test func something()` |
| `XCTAssertEqual(a, b)` | `#expect(a == b)` |
| `XCTAssertThrowsError` | `#expect(throws: ErrorType.self)` |
| `XCTUnwrap(optional)` | `try #require(optional)` |
| `setUp()` / `tearDown()` | `init()` / `deinit` |
| `XCTSkipIf(condition)` | `try #require(condition)` or `.enabled(if:)` |

**Migration strategy:** Write new tests with Swift Testing. Migrate existing XCTest files gradually. Use `swift-testing-revolutionary` or `Testpiler` tools to automate syntax conversion. Peter Steinberger migrated 700+ tests across 118 files — consolidating into nested suites reduced file count by 46%.

**Cannot migrate:** UI automation tests and performance tests (`XCTMetric`) — these are not supported by Swift Testing.

### Dependency Injection for Testability

```swift
// Protocol for mockability
protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(_ path: String) async throws -> T
}

// Production implementation
final class APIClient: APIClientProtocol {
    static let shared = APIClient()
    func get<T: Decodable>(_ path: String) async throws -> T { ... }
}

// Test mock
final class MockAPIClient: APIClientProtocol {
    var shouldFail = false
    var mockData: Any?

    func get<T: Decodable>(_ path: String) async throws -> T {
        if shouldFail { throw NetworkError.serverError }
        return mockData as! T
    }
}

// Store accepts protocol
@Observable
final class BookStore {
    private let apiClient: any APIClientProtocol

    init(apiClient: any APIClientProtocol = APIClient.shared) {
        self.apiClient = apiClient
    }
}
```

---

## 9. Code Style & Conventions

### Naming (based on Apple API Design Guidelines + Google Swift Style Guide)

```swift
// Types: UpperCamelCase
struct BookMetadata { }
enum LoadingState { }
protocol Fetchable { }

// Everything else: lowerCamelCase
var bookCount: Int
func fetchBooks() async { }
let maxRetryCount = 3

// Boolean properties read as assertions
var isEmpty: Bool
var hasUnsavedChanges: Bool
var shouldAutoRefresh: Bool

// Factory methods
static func makeDefault() -> Configuration { }

// Constants: lowerCamelCase (no k-prefix, no UPPER_SNAKE)
let defaultTimeout: TimeInterval = 30
static let maximumRetries = 3
```

### Formatting Rules

- **Line length:** 100 characters (Google) or 120 (Apple). Pick one, enforce with SwiftLint.
- **Braces:** K&R style (opening brace on same line)
- **No semicolons**
- **Trailing commas** in multi-line collection literals
- **One statement per line**

### Access Control

```swift
// Default to most restrictive. Only expose what's needed.
public struct APIResponse<T: Decodable> {
    public let data: T
    public let statusCode: Int

    // Internal by default — accessible within module
    let headers: [String: String]

    // Private — only within this type
    private let rawData: Data
}

// Use private(set) for read-only external access
@Observable
final class Store {
    private(set) var items: [Item] = []  // External can read, only Store can write

    func addItem(_ item: Item) {
        items.append(item)
    }
}
```

### Error Handling

```swift
// Define domain-specific errors
enum BookError: LocalizedError {
    case notFound(id: String)
    case invalidFormat
    case networkFailure(underlying: Error)

    var errorDescription: String? {
        switch self {
        case .notFound(let id): "Book '\(id)' not found"
        case .invalidFormat: "Invalid book format"
        case .networkFailure(let error): "Network error: \(error.localizedDescription)"
        }
    }
}

// Use guard for early exits
func processBook(_ book: Book?) throws -> ProcessedBook {
    guard let book else {
        throw BookError.invalidFormat
    }
    guard !book.title.isEmpty else {
        throw BookError.invalidFormat
    }
    return ProcessedBook(book)
}
```

### SwiftLint

Use SwiftLint for automated style enforcement. Recommended starting config:

```yaml
# .swiftlint.yml
disabled_rules:
  - trailing_whitespace

opt_in_rules:
  - empty_count
  - closure_spacing
  - force_unwrapping
  - implicitly_unwrapped_optional
  - private_outlet
  - sorted_imports

line_length:
  warning: 120
  error: 200

type_body_length:
  warning: 300
  error: 500

file_length:
  warning: 500
  error: 1000

excluded:
  - Packages
  - .build
```

---

## 10. Dependencies & Package Management

### Swift Package Manager (SPM) — The Default

SPM is the standard dependency manager. CocoaPods is legacy; Carthage is niche. Use SPM unless a dependency forces otherwise.

```swift
// Package.swift for a local package
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NetworkKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "NetworkKit", targets: ["NetworkKit"]),
    ],
    dependencies: [
        // Pin to exact versions or ranges
        .package(url: "https://github.com/apple/swift-collections.git", from: "1.1.0"),
    ],
    targets: [
        .target(
            name: "NetworkKit",
            dependencies: [
                .product(name: "Collections", package: "swift-collections"),
            ]
        ),
        .testTarget(
            name: "NetworkKitTests",
            dependencies: ["NetworkKit"]
        ),
    ]
)
```

### Recommended Libraries (2025-2026)

| Need | Library | Notes |
|------|---------|-------|
| Networking | URLSession (built-in) | async/await native. Alamofire is rarely needed now. |
| JSON | Codable (built-in) | Use `JSONDecoder`/`JSONEncoder`. |
| Images | Kingfisher or Nuke | AsyncImage is fine for simple cases. |
| Keychain | KeychainAccess | Thin wrapper over Security framework. |
| Logging | os.Logger (built-in) | `import os; let logger = Logger(subsystem:category:)` |
| Collections | swift-collections | OrderedSet, Deque, etc. from Apple. |
| Algorithms | swift-algorithms | Chunks, windows, combinations from Apple. |
| DI (if using TCA) | swift-dependencies | Point-Free's DI system. |
| Navigation (if using TCA) | swift-navigation | Point-Free's navigation library. |
| Linting | SwiftLint | Essential for team projects. |

**Libraries to avoid or reconsider:**
- **Combine** — effectively deprecated in favor of Observation + async/await
- **RxSwift** — even more legacy than Combine in the Swift context
- **Alamofire** — URLSession with async/await covers most use cases
- **CocoaPods** — migrate to SPM if possible

---

## 11. Common Anti-Patterns

### Concurrency & Safety Anti-Patterns

**@Observable ViewModels must be @MainActor:**
```swift
// WRONG — @unchecked Sendable suppresses compiler safety checks
@Observable
final class FeedViewModel: @unchecked Sendable { ... }

// RIGHT — @MainActor already provides Sendable conformance
@MainActor @Observable
final class FeedViewModel { ... }
```

**Never force-unwrap firstIndex in @Observable-backed views:**
```swift
// WRONG — array can mutate between search and dereference
let index = items.firstIndex(where: { $0.id == id })!

// RIGHT — guard against concurrent mutation
guard let index = items.firstIndex(where: { $0.id == id }) else { return }
```

**Static formatters — never instantiate in computed properties or render closures:**
```swift
// WRONG — creates new formatter every render cycle
var formattedDate: String { DateFormatter().string(from: date) }

// RIGHT — static allocation, reused
static let dateFormatter: DateFormatter = { let f = DateFormatter(); f.dateStyle = .medium; return f }()
```

**Mock protocol stubs in Swift Testing:**
```swift
// WRONG — fatalError crashes entire test suite
func unusedMethod() { fatalError("Not implemented") }

// RIGHT — typed error fails just the one test
func unusedMethod() throws { throw APIError.connectionError("Not implemented in mock") }
```

### Architecture Anti-Patterns

**1. ViewModel for every view**
```swift
// WRONG — unnecessary layer
struct SimpleTextView: View {
    @State var viewModel = SimpleTextViewModel()
    var body: some View { Text(viewModel.text) }
}

// RIGHT — just use the value directly
struct SimpleTextView: View {
    let text: String
    var body: some View { Text(text) }
}
```

**2. Massive observable classes**
```swift
// WRONG — god object
@Observable class AppState {
    var user: User?
    var books: [Book] = []
    var settings: Settings = .init()
    var notifications: [Notification] = []
    // ... 50 more properties
}

// RIGHT — separate stores per domain
@Observable final class UserStore { var user: User? }
@Observable final class BookStore { var books: [Book] = [] }
@Observable final class SettingsStore { var settings = Settings() }
```

**3. Force unwrapping outside tests**
```swift
// WRONG
let url = URL(string: userInput)!

// RIGHT
guard let url = URL(string: userInput) else {
    throw AppError.invalidURL(userInput)
}
```

### SwiftUI Anti-Patterns

**4. Heavy computation in view body**
```swift
// WRONG — runs on every render
var body: some View {
    let sorted = items.sorted { expensiveComparison($0, $1) }
    List(sorted) { item in ItemRow(item: item) }
}

// RIGHT — compute in the store or cache
var body: some View {
    List(store.sortedItems) { item in ItemRow(item: item) }
}
```

**5. Mixing DispatchQueue with Swift Concurrency**
```swift
// WRONG
DispatchQueue.global().async {
    let data = processData()
    DispatchQueue.main.async {
        self.result = data
    }
}

// RIGHT
@concurrent
func processData() async -> Data { ... }

func handleData() async {
    result = await processData()
}
```

---

## 12. Framework Maturity Assessment

As of March 2026:

| Framework | Maturity | Verdict |
|-----------|----------|---------|
| **SwiftUI** | Mature (7 years old). Major improvements yearly. | **Use for new apps.** Bridge UIKit/AppKit for gaps. |
| **Swift Concurrency** | Mature with Swift 6.2. "Approachable" model is production-ready. | **Adopt.** Swift 6.2 is dramatically simpler than Swift 5.x concurrency. |
| **Observation (@Observable)** | Stable since Swift 5.9. `Observations` streaming added in 6.2. | **Adopt.** Replace Combine/ObservableObject. |
| **SwiftData** | Usable for simple-medium apps. Critical bugs fixed. | **Adopt for new simple apps.** Use Core Data for CloudKit sharing or complex needs. |
| **Core Data** | No new features since WWDC23. Not deprecated. | **Keep for existing apps** and CloudKit sharing. |
| **Combine** | No updates since 2021. Effectively succeeded by Observation + async/await. | **Don't adopt for new code.** Maintain existing. |
| **Swift Testing** | Shipping since Xcode 16. Actively developed. | **Adopt for new tests.** Migrate XCTest gradually. |
| **TCA** | v1.x stable. v2 in preview. Active development. | **Consider for complex apps.** Overkill for simple ones. |

### What to Watch

- **TCA 2** — Major simplification coming. Worth re-evaluating if you dismissed TCA before.
- **SwiftData CloudKit sharing** — Highly requested, not yet available. Will change the Core Data calculus when it arrives.
- **Swift on the web (WebAssembly)** — Swift 6.2 adds Wasm support. Early days but official Apple investment.
- **Liquid Glass** — New design language requires Xcode 26 recompile. Test thoroughly for visual regressions.

---

## Sources

- [WWDC25: Embracing Swift Concurrency](https://developer.apple.com/videos/play/wwdc2025/268/) — Apple's official concurrency guidance
- [WWDC25: What's New in Swift](https://developer.apple.com/wwdc25/guides/swift/) — Swift 6.2 features
- [WWDC25: What's New in SwiftUI](https://developer.apple.com/wwdc25/guides/swiftui) — SwiftUI updates
- [SwiftUI 2025: What's Fixed, What's Not](https://juniperphoton.substack.com/p/swiftui-2025-whats-fixed-whats-not) — Honest assessment of SwiftUI state
- [SwiftUI for Mac 2025](https://troz.net/post/2025/swiftui-mac-2025/) — macOS-specific SwiftUI guide
- [Problematic Swift Concurrency Patterns](https://www.massicotte.org/problematic-patterns/) — Anti-patterns catalog
- [Swift Forums: Apple's Architecture Stance](https://forums.swift.org/t/what-is-the-architecture-officially-recommended-by-apple-for-swiftui-applications/44930) — No official recommendation
- [Thomas Ricouard: Forget MVVM in SwiftUI](https://dimillian.medium.com/swiftui-in-2025-forget-mvvm-262ff2bbd2ed) — Case against MVVM
- [Point-Free 2025 Year in Review](https://www.pointfree.co/blog/posts/196-2025-year-in-review) — TCA 2 preview, new tools
- [Streaming Changes with Observations](https://swiftwithmajid.com/2025/07/30/streaming-changes-with-observations/) — Observations async sequence
- [Key Considerations Before Using SwiftData](https://fatbobman.com/en/posts/key-considerations-before-using-swiftdata/) — SwiftData pitfalls
- [SwiftData and Core Data at WWDC25](https://mjtsai.com/blog/2025/06/19/swiftdata-and-core-data-at-wwdc25/) — Community perspective
- [Swift 6.2 Approachable Concurrency](https://mjtsai.com/blog/2025/11/03/swift-6-2-approachable-concurrency/) — Developer reactions
- [Migrating 700+ Tests to Swift Testing](https://steipete.me/posts/2025/migrating-700-tests-to-swift-testing) — Real-world migration
- [Clean Architecture for SwiftUI](https://nalexn.github.io/clean-architecture-swiftui/) — Three-layer pattern
- [Google Swift Style Guide](https://google.github.io/swift/) — Coding conventions
- [Lickability Swift Best Practices](https://github.com/Lickability/swift-best-practices) — Team practices
- [Apple Developer: Observation Framework](https://developer.apple.com/documentation/Observation) — Official docs
