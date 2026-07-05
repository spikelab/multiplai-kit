# SwiftUI macOS-Specific Best Practices (2026)

Patterns and guidance specific to macOS development with SwiftUI. This complements `swift-best-practices.md` (which covers shared iOS/macOS patterns) with depth on macOS-only concerns.

**Last updated:** 2026-03-14
**Swift version:** 6.2 (Xcode 26)
**Minimum deployment:** macOS 14+ recommended
**Research source:** `INBOX/swift-macos-best-practices-2026-03-14.md`

---

## Table of Contents

1. [When SwiftUI Is Not Enough (AppKit Bridging)](#1-when-swiftui-is-not-enough)
2. [Window Management](#2-window-management)
3. [App Lifecycle & NSApplicationDelegate](#3-app-lifecycle)
4. [Global Hotkeys](#4-global-hotkeys)
5. [MenuBarExtra Patterns](#5-menubarextra-patterns)
6. [Toolbar Patterns](#6-toolbar-patterns)
7. [Drag and Drop](#7-drag-and-drop)
8. [Sandboxing & Entitlements](#8-sandboxing--entitlements)
9. [Security-Scoped Bookmarks](#9-security-scoped-bookmarks)
10. [Distribution & Notarization](#10-distribution--notarization)
11. [XPC Services](#11-xpc-services)
12. [macOS-Specific Modifiers](#12-macos-specific-modifiers)
13. [Dock Integration](#13-dock-integration)
14. [System Integration (URL Schemes, UTTypes)](#14-system-integration)
15. [Liquid Glass / macOS Tahoe](#15-liquid-glass)
16. [Container Development Notes](#16-container-development-notes)

---

## 1. When SwiftUI Is Not Enough

SwiftUI is production-ready for most macOS apps in 2026. Use AppKit selectively, not as a parallel framework.

### Use AppKit When You Need

- **Fine-grained menu bar control** — SwiftUI's `CommandGroup`/`CommandMenu` cannot remove individual standard menus (e.g., remove File menu while keeping others)
- **Mouse tracking** — `NSTrackingArea` for precise cursor behavior beyond `onHover`
- **Dock menu customization** — `applicationDockMenu(_:)` has no SwiftUI equivalent
- **Advanced window behaviors** — `NSWindowDelegate` callbacks not exposed in SwiftUI
- **Lists beyond ~20,000 items** — `NSTableView`/`NSOutlineView` remain superior at scale

### NSViewRepresentable Pattern

```swift
struct AppKitTextView: NSViewRepresentable {
    @Binding var text: String

    func makeNSView(context: Context) -> NSTextView {
        let textView = NSTextView()
        textView.delegate = context.coordinator
        textView.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        return textView
    }

    func updateNSView(_ nsView: NSTextView, context: Context) {
        if nsView.string != text {
            nsView.string = text
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    class Coordinator: NSObject, NSTextViewDelegate {
        let parent: AppKitTextView
        init(_ parent: AppKitTextView) { self.parent = parent }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textView.string
        }
    }
}
```

### Reverse Direction (SwiftUI in AppKit)

```swift
let hostingView = NSHostingView(rootView: MySwiftUIView())
hostingView.frame = parentView.bounds
parentView.addSubview(hostingView)
```

---

## 2. Window Management

macOS window management in SwiftUI is mature since WWDC24.

### Five Scene Types

| Scene | Instances | Use Case |
|-------|-----------|----------|
| `WindowGroup` | Multiple | Main app windows, data-driven content |
| `Window` | Single | About panel, utilities, inspector |
| `DocumentGroup` | Multiple | File-based apps |
| `Settings` | Single | Preferences (auto-enables menu item) |
| `MenuBarExtra` | Single | Menu bar utilities |

All scene types can be composed in a single app.

### Programmatic Window Control

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
            .defaultSize(width: 900, height: 600)

        Window("Inspector", id: "inspector") {
            InspectorView()
        }
        .defaultWindowPlacement { content, context in
            let displayBounds = context.defaultDisplay.visibleRect
            let size = content.sizeThatFits(.unspecified)
            return WindowPlacement(size: size)
        }
        .restorationBehavior(.disabled)

        Settings { SettingsView() }
    }
}

// Opening/closing windows from any view:
@Environment(\.openWindow) var openWindow
@Environment(\.dismiss) var dismiss

Button("Show Inspector") { openWindow(id: "inspector") }
```

### Window Styles (WWDC24)

```swift
// Borderless window (custom chrome)
.windowStyle(.plain)

// Disable minimize
.windowMinimizeBehavior(.disabled)

// Disable state restoration (for utility/About windows)
.restorationBehavior(.disabled)

// Position based on display
.defaultWindowPlacement { content, context in
    WindowPlacement(size: content.sizeThatFits(.unspecified))
}

// Zoom button behavior
.windowIdealPlacement { content, context in
    WindowPlacement(size: CGSize(width: 1200, height: 800))
}

// Auto-present on launch
.defaultLaunchBehavior(.presented)

// Frosted glass background
.containerBackground(.thickMaterial, for: .window)

// Constrain size (disables full-screen when max is restrictive)
.windowResizability(.contentSize)
```

### Preventing Duplicate Windows

`WindowGroup` with `id` does NOT prevent duplicates. Use:
- `Window` scene for single-instance windows
- `WindowGroup(for: Type.self)` with data values for content-dependent uniqueness

### State Management Across Windows

- `@SceneStorage` — per-window persistence (survives close/reopen)
- `@AppStorage` — app-wide (shared across all windows)
- `NotificationCenter` — inter-window communication
- **Do NOT** share `@StateObject` from App struct — it's shared across all window instances

---

## 3. App Lifecycle

### NSApplicationDelegate Integration

Apple warns against AppDelegate but provides no SwiftUI alternative for many macOS features.

```swift
class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Quick Action",
                                action: #selector(quickAction), keyEquivalent: ""))
        return menu
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true  // Fix for quit-on-close when secondary windows exist
    }

    @objc func quickAction() { /* ... */ }
}

@main
struct MyApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup { ContentView() }
    }
}
```

### When AppDelegate Is Still Needed

- Dock menu customization
- Global menu commands beyond `CommandGroup`/`CommandMenu`
- Complex app termination logic
- Push notification handling
- Single-window-app quit-on-close when secondary windows exist

### ScenePhase Limitations on macOS

Individual scene `.scenePhase` is **unreliable** on macOS. Only App-level aggregate `ScenePhase` accurately reflects application state. For termination cleanup, monitor `.background` at App level.

### Best Practice

Move as much AppDelegate logic as possible into `@Observable` classes. Keep AppDelegate minimal. **Caution:** Retaining AppDelegate may break Xcode previews.

---

## 4. Global Hotkeys

Apple provides **no modern API** for global keyboard shortcuts. Two libraries wrap the deprecated-but-maintained Carbon `RegisterEventHotKey` API.

### Library Comparison

| Feature | KeyboardShortcuts | HotKey |
|---------|-------------------|--------|
| User-customizable | Yes (built-in Recorder UI) | No (hard-coded only) |
| SwiftUI support | Built-in `Recorder` view | None |
| Sandbox/MAS compatible | Yes | Yes |
| Persistence | Automatic (UserDefaults) | Manual |
| Permission dialogs | None required | None required |
| API complexity | More features | Single line |

### KeyboardShortcuts (Recommended for user-facing apps)

```swift
import KeyboardShortcuts

extension KeyboardShortcuts.Name {
    static let toggleApp = Self("toggleApp",
        default: .init(.space, modifiers: [.command, .option]))
}

// In Settings:
KeyboardShortcuts.Recorder("Activate:", name: .toggleApp)

// Register handler (e.g., in App init or onAppear):
KeyboardShortcuts.onKeyUp(for: .toggleApp) {
    NSApp.activate(ignoringOtherApps: true)
}
```

### HotKey (Simplest for fixed shortcuts)

```swift
import HotKey

@main
struct MyApp: App {
    let hotKey = HotKey(key: .space, modifiers: [.command, .option],
                        keyDownHandler: {
                            NSApp.activate(ignoringOtherApps: true)
                        })
    var body: some Scene { /* ... */ }
}
```

### Key Facts

- Neither library requires Accessibility permissions (they use Carbon APIs, not event taps)
- Both are sandbox-compatible and Mac App Store approved
- Carbon API risk: if Apple deprecates without replacement, both break. No deprecation signal so far.
- Cannot capture media keys or Caps Lock

---

## 5. MenuBarExtra Patterns

`MenuBarExtra` (macOS 13+) supports two styles.

### Two Styles

- **`.menu`** — standard macOS menu (limited to text, buttons, dividers; button styles ignored)
- **`.window`** — full SwiftUI view hierarchy (rich controls, custom layouts)

### Menu-Bar-Only App

```swift
@main
struct StatusApp: App {
    var body: some Scene {
        MenuBarExtra("Status", systemImage: "gear") {
            VStack {
                StatusView()
                Divider()
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
        }
        .menuBarExtraStyle(.window)
    }
}
```

Hide from Dock: set `LSUIElement = YES` in Info.plist.

### SettingsLink Workaround

`SettingsLink` does not work in MenuBarExtra (menu bar apps use `.accessory` activation policy, lack foreground context).

Workaround requires a hidden `Window` + `NSApp.setActivationPolicy(.regular)` + `NotificationCenter` decoupling. The hidden Window must be declared **before** the Settings scene.

For full control, use [MenuBarExtraAccess](https://github.com/orchetect/MenuBarExtraAccess) — provides binding-based presentation control and `NSStatusItem` access.

### Composing With Other Scenes

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }       // Main window
        Settings { SettingsView() }          // Preferences
        MenuBarExtra("Status", systemImage: "circle.fill") {
            QuickStatusView()
        }
        .menuBarExtraStyle(.window)
    }
}
```

---

## 6. Toolbar Patterns

SwiftUI supports native customizable toolbars on macOS via `toolbar(id:)`.

### Customizable Toolbar

```swift
.toolbar(id: "mainToolbar") {
    ToolbarItem(id: "newDoc", placement: .navigation) {
        Button("New", systemImage: "doc.badge.plus") { }
    }
    ToolbarItem(id: "share") {
        Button("Share", systemImage: "square.and.arrow.up") { }
            .defaultCustomization(.hidden)  // Only in customize palette
    }
}
```

User customizations are automatically saved and restored. Use `ControlGroup` for items that customize as a unit.

### Toolbar Styles

```swift
.windowToolbarStyle(.expanded)          // Full-height
.windowToolbarStyle(.unifiedCompact)    // Compact unified

// Transparent toolbar
.toolbarBackgroundVisibility(.hidden, for: .windowToolbar)

// Remove title
.toolbar(removing: .title)

// Colored toolbar background
.toolbarBackground(.blue, for: .windowToolbar)
```

### Spacing (macOS 26+)

```swift
ToolbarSpacer(.fixed)       // Fixed space
ToolbarSpacer(.flexible)    // Flexible space
```

### Known Bug

Segmented picker near search field can become trapped in the chevron menu (Apple bug FB17392294). Workaround: position picker before search field.

---

## 7. Drag and Drop

### Within-App (Transferable Protocol)

```swift
struct Item: Codable, Transferable, Hashable {
    let id: UUID
    let name: String

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .item)
    }
}

// Drag source
Text(item.name)
    .draggable(item)

// Drop target
List { /* ... */ }
    .dropDestination(for: Item.self) { items, location in
        // Handle dropped items
        return true
    }
```

### Inter-App File Drops

```swift
.onDrop(of: [.fileURL], isTargeted: nil) { providers in
    for provider in providers {
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) { data, error in
            guard let data = data as? Data,
                  let url = URL(dataRepresentation: data, relativeTo: nil)
            else { return }
            DispatchQueue.main.async {
                handleDroppedFile(url)
            }
        }
    }
    return true
}
```

**Note:** `NSItemProvider` loads items on background queue. Always dispatch UI updates to main queue.

### Advanced: DropDelegate

For precise drop positioning and validation:

```swift
struct MyDropDelegate: DropDelegate {
    func validateDrop(info: DropInfo) -> Bool {
        info.hasItemsConforming(to: [.fileURL])
    }

    func performDrop(info: DropInfo) -> Bool {
        // Handle drop
        return true
    }
}
```

---

## 8. Sandboxing & Entitlements

### When Sandbox Is Required

- **Mac App Store:** Required
- **Direct distribution:** Optional but recommended
- **Apps managing Docker/processes:** Skip sandbox, use hardened runtime only

### Core Entitlements

```xml
<!-- Enable sandbox -->
<key>com.apple.security.app-sandbox</key>
<true/>

<!-- Network: outgoing connections (WebSocket, API calls) -->
<key>com.apple.security.network.client</key>
<true/>

<!-- Network: incoming connections (local server) -->
<key>com.apple.security.network.server</key>
<true/>

<!-- File access: user-selected files -->
<key>com.apple.security.files.user-selected.read-write</key>
<true/>

<!-- Persistent file access via bookmarks -->
<key>com.apple.security.files.bookmarks.app-scope</key>
<true/>
```

### Hardened Runtime

Required for notarization and Developer ID distribution. Enable in Xcode: Signing & Capabilities > Hardened Runtime.

Key hardened runtime entitlements:
- `com.apple.security.cs.allow-unsigned-executable-memory` — for JIT or dynamic code
- `com.apple.security.cs.disable-library-validation` — for loading third-party frameworks

For direct distribution without sandbox: hardened runtime + notarization are still mandatory (since Catalina).

---

## 9. Security-Scoped Bookmarks

Persistent access to user-selected files/folders outside the sandbox, surviving app restarts.

### Complete Lifecycle

```swift
// 1. User selects folder
let panel = NSOpenPanel()
panel.canChooseDirectories = true
panel.canChooseFiles = false
if panel.runModal() == .OK, let url = panel.url {

    // 2. Create security-scoped bookmark
    let bookmarkData = try url.bookmarkData(
        options: .withSecurityScope,
        includingResourceValuesForKeys: nil,
        relativeTo: nil
    )

    // 3. Persist to UserDefaults
    UserDefaults.standard.set(bookmarkData, forKey: "myBookmark")
}

// 4. Later: resolve bookmark
var isStale = false
let url = try URL(
    resolvingBookmarkData: savedData,
    options: .withSecurityScope,
    relativeTo: nil,
    bookmarkDataIsStale: &isStale
)

// 5. MUST check staleness — regenerate if true
if isStale { /* Re-create from fresh user selection */ }

// 6. Access pattern (MUST balance start/stop)
guard url.startAccessingSecurityScopedResource() else { return }
defer { url.stopAccessingSecurityScopedResource() }
// ... file operations ...
```

### Critical Rules

- **Failing to call `stopAccessingSecurityScopedResource()` leaks kernel resources.** The app cannot add new sandbox locations until relaunched.
- Always check `bookmarkDataIsStale` and regenerate if true.
- **macOS Sequoia bug:** `ScopedBookmarksAgent` could hang when keychain was locked. Fixed in macOS 15.1.

### Required Entitlements

`com.apple.security.files.bookmarks.app-scope` + `com.apple.security.files.user-selected.read-write`

---

## 10. Distribution & Notarization

### Comparison

| Aspect | Mac App Store | Direct (Developer ID) |
|--------|--------------|----------------------|
| Sandbox | Required | Optional |
| Hardened Runtime | Automatic | Required |
| Notarization | Not needed | Required |
| Updates | App Store handles | You handle (Sparkle) |
| Revenue share | 30%/15% | None |
| Review process | Yes (days) | Notarization only (minutes) |
| System extensions | Limited | Full access |

### Notarization Workflow (Mandatory for Direct)

```bash
# 1. Archive and export
# Xcode: Product > Archive > Distribute App > Direct Distribution > Export

# 2. Store credentials (one-time)
xcrun notarytool store-credentials "AC_PASSWORD" \
    --apple-id you@email.com --team-id YOURTEAMID

# 3. Create DMG
brew install create-dmg
create-dmg "MyApp.dmg" "MyApp.app"

# 4. Submit for notarization
xcrun notarytool submit MyApp.dmg \
    --keychain-profile "AC_PASSWORD" --wait

# 5. Staple ticket to DMG
xcrun stapler staple MyApp.dmg
```

**`altool` is dead** since November 2023. Use `notarytool` exclusively.

### Sparkle for Auto-Updates

[Sparkle 2.8](https://github.com/sparkle-project/Sparkle) is the standard for direct distribution auto-updates. Features: EdDSA + code signing verification, delta updates, sandbox support, beta channels, phased rollouts. macOS Tahoe compatible.

### Dual Distribution (App Store + Direct)

Use single target with `SPARKLE` compiler directive and separate build configurations:

```swift
#if SPARKLE
import Sparkle
let updaterController = SPUStandardUpdaterController(
    startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
#endif
```

**SPM cannot conditionally link frameworks** — manual framework integration required with build phase scripts to strip Sparkle from App Store builds.

---

## 11. XPC Services

Crash isolation, privilege separation, and entitlement separation for macOS apps.

### Architecture

- XPC services live in `Contents/XPCServices/` of app bundle
- `launchd` manages lifecycle: on-demand spawn, idle termination, crash restart
- All XPC method calls are asynchronous
- Each service can have its own entitlements

### Protocol Pattern

```swift
@objc protocol DockerServiceProtocol {
    func listContainers(withReply reply: @escaping ([String]) -> Void)
    func startContainer(_ id: String, withReply reply: @escaping (Bool) -> Void)
}
```

### When To Use

- **Docker/process management** — isolate shell execution from main app (crash in Docker ops doesn't crash UI)
- **Network operations** — separate WebSocket service for crash isolation
- **Privilege separation** — only the service that needs shell access gets those entitlements

### Limitation

XPC services cannot present UI. Build SwiftUI frontend in main app, communicate with XPC services for privileged operations.

### Recommendation

XPC is a later optimization, not day-one. Start with everything in-process, extract to XPC when you need crash isolation or entitlement separation.

---

## 12. macOS-Specific Modifiers

### Hover and Cursor

```swift
Text("Hover me")
    .onHover { isHovering in
        // Change appearance
    }

// Cursor changes (requires AppKit bridging)
.onHover { hovering in
    if hovering {
        NSCursor.pointingHand.push()
    } else {
        NSCursor.pop()
    }
}
```

### Context Menus (Right-Click)

```swift
Text("Right-click me")
    .contextMenu {
        Button("Copy") { }
        Button("Delete", role: .destructive) { }
        Menu("Share") {
            Button("Email") { }
            Button("Messages") { }
        }
    }
```

### Popovers

```swift
.popover(isPresented: $showPopover, arrowEdge: .bottom) {
    PopoverContent()
        .frame(width: 300, height: 200)
}
```

On macOS, popovers appear as actual popover windows (not sheets as on compact iOS).

### Control Sizes

```swift
Button("Small") { }
    .controlSize(.small)
// Options: .mini, .small, .regular, .large, .extraLarge (macOS Tahoe)
```

### Focusable

Makes non-interactive views participate in keyboard navigation — important for accessibility:

```swift
Text("Focusable text")
    .focusable()
```

---

## 13. Dock Integration

### Dock Menus

Require `NSApplicationDelegate` — no pure SwiftUI API. The `applicationDockMenu(_:)` method has known reliability issues in SwiftUI lifecycle (sometimes called only once after launch).

```swift
func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
    let menu = NSMenu()
    menu.addItem(NSMenuItem(title: "New Window",
                            action: #selector(newWindow), keyEquivalent: ""))
    return menu
}
```

### Dock Badges

Use [DSFDockTile](https://github.com/dagronf/DSFDockTile) for badge labels, custom images, and animations. Due to `NSDockTile` restrictions, the view is not drawn live — call `display()` to update.

---

## 14. System Integration

### URL Schemes

Register in Info.plist under URL Types, handle with `.onOpenURL`:

```swift
WindowGroup {
    ContentView()
        .onOpenURL { url in
            // Handle myapp://action URLs
            handleDeepLink(url)
        }
}
```

### File Type Associations (UTType)

```swift
import UniformTypeIdentifiers

extension UTType {
    static let myDocument = UTType(exportedAs: "com.yourapp.document")
}
```

Register in Info.plist under `CFBundleDocumentTypes` with the UTType identifier.

### Services Menu

No SwiftUI API. Requires AppKit: `NSApplication.registerServicesMenuSendTypes`. Limited modern documentation.

---

## 15. Liquid Glass

Apple's unified design language (WWDC 2025 / macOS Tahoe / macOS 26).

### What's Automatic

Recompiling with Xcode 26 applies Liquid Glass to: toolbars, sidebars, menus, window controls, popovers, sheets, toggles, sliders, pickers. Zero code changes.

### New APIs

```swift
// Glass effects
.glassEffect(.regular)                    // Standard
.glassEffect(.clear)                      // Over media content only
.glassEffect(.regular, in: .capsule)      // With shape

// Button styles
.buttonStyle(.glass)                      // Secondary actions
.buttonStyle(.glassProminent)             // Primary actions (tinted)

// Grouping (REQUIRED for multiple glass elements)
GlassEffectContainer(spacing: 16) {
    HStack {
        Button("A") { }.glassEffect()
        Button("B") { }.glassEffect()
    }
}

// Morphing animations
.glassEffectID("myElement", in: namespace)
```

### Golden Rules

1. Glass is for **navigation layers** (toolbars, floating buttons) — never content layers
2. "Glass cannot sample other glass" — always use `GlassEffectContainer`
3. Never mix `.regular` and `.clear` variants in the same view
4. Tint primary actions only, never multiple elements

### Opt-Out

`UIDesignRequiresCompatibility = YES` in Info.plist delays adoption. This flag will be removed in Xcode 27 — Liquid Glass becomes mandatory.

### Terminal-Aesthetic UI Warning

Content blurring behind toolbar/title bar "ends up looking like a layout error much of the time" (real developer feedback). For dark/terminal-style UIs:

```swift
// Control toolbar transparency
.toolbarBackgroundVisibility(.hidden, for: .windowToolbar)

// Borderless window for full control
.windowStyle(.plain)

// Opaque container background
.containerBackground(.black, for: .window)
```

### Accessibility

Automatic. Reduce Transparency makes glass frostier. Increase Contrast renders black/white with borders. No additional code needed.

### AppKit

`NSButton.bezelStyle = .glass` and `NSToolbarItemGroup` for toolbar grouping.

---

## 16. Container Development Notes

When developing macOS apps from inside Docker containers (via the `swift-host.sh` SSH bridge):

### What Requires macOS Host Testing

These patterns invoke macOS-only frameworks and **cannot be tested via `swift test` in a container**:

- Window management (all Scene types, `openWindow`, window styles)
- Global hotkeys (KeyboardShortcuts, HotKey — Carbon APIs)
- MenuBarExtra behavior
- Toolbar rendering and customization
- Drag and drop (requires UI runtime)
- AppKit bridging (NSViewRepresentable, NSHostingView)
- Dock integration
- Liquid Glass visual effects
- Security-scoped bookmark dialogs (NSOpenPanel)

### What's Testable in Containers (`swift test`)

Extract logic into ViewModels and test without macOS:

- Business logic and state management
- WebSocket connection logic (protocol, encoding, reconnection)
- Data models and Codable conformance
- Navigation decision logic (which window to show, what state to pass)
- Notification/event handling logic (minus the actual notification delivery)
- ViewModel state transitions for all user actions
- Docker container management logic (API calls, state tracking)
- File bookmark data management (encoding/decoding, staleness checks — minus the actual OS dialog)

### Build/Test Commands

```bash
# All commands go through swift-host.sh — never raw SSH
$CLAUDE_CONFIG_DIR/skills/swift-build/scripts/swift-host.sh build
$CLAUDE_CONFIG_DIR/skills/swift-build/scripts/swift-host.sh test
$CLAUDE_CONFIG_DIR/skills/swift-build/scripts/swift-host.sh test --filter MyTests

# With --package-path for non-cwd projects
$CLAUDE_CONFIG_DIR/skills/swift-build/scripts/swift-host.sh --package-path /path/to/project test
```

The script auto-detects local macOS vs container and routes through SSH accordingly. See `swift-build` skill docs for full details.

### App Launch Verification

**CRITICAL:** `swift build` and `swift test` succeeding does NOT mean the app can launch. A library-only SwiftPM package compiles and passes all tests but has no entry point. Always verify:

1. Package.swift has an `.executableTarget` with `@main` — see "SwiftPM App Target Pattern" in `swift-best-practices.md`
2. `swift run --package-path <path>` actually launches the app (not just exits 0)
3. The executable target contains ONLY the `@main` App struct; all code lives in the library target for testability

---

## Sources

Primary sources consulted for this document:

1. [WWDC24: Tailor macOS Windows](https://developer.apple.com/videos/play/wwdc2024/10148/) — Window management APIs
2. [Apple Developer ID](https://developer.apple.com/developer-id/) — Distribution requirements
3. [SwiftUI for Mac 2025 (TrozWare)](https://troz.net/post/2025/swiftui-mac-2025/) — macOS 26 overview
4. [AppKit to SwiftUI (smittytone)](https://blog.smittytone.net/2025/03/25/macos-development-appkit-swift-ui/) — Migration experience
5. [Settings from MenuBarExtra (Steinberger)](https://steipete.me/posts/2025/showing-settings-from-macos-menu-bar-items) — MenuBarExtra workarounds
6. [Liquid Glass Best Practices](https://dev.to/diskcleankit/liquid-glass-in-swift-official-best-practices-for-ios-26-macos-tahoe-1coo) — Implementation guide
7. [SwiftUI Lifecycle (Eclectic Light)](https://eclecticlight.co/2024/04/17/swiftui-on-macos-life-cycle-and-appdelegate/) — AppDelegate patterns
8. [Scene Types (nilcoalescing)](https://nilcoalescing.com/blog/ScenesTypesInASwiftUIMacApp/) — macOS scene types
9. [Security Bookmarks (SwiftLee)](https://www.avanderlee.com/swift/security-scoped-bookmarks-for-url-access/) — Bookmark patterns
10. [Security Bookmarks (AppCoda)](https://www.appcoda.com/mac-apps-user-intent/) — Full lifecycle
11. [Sparkle Distribution (SwiftLee)](https://www.avanderlee.com/xcode/sparkle-distribution-apps-in-and-out-of-the-mac-app-store/) — Dual distribution
12. [Toolbar Examples (Ohanaware)](https://ohanaware.com/swift/macOSToolbarExamples.html) — Customizable toolbars
13. [Drag and Drop (Eclectic Light)](https://eclecticlight.co/2024/05/21/swiftui-on-macos-drag-and-drop-and-more/) — DropDelegate patterns
14. [Window Management (FlineDev)](https://fline.dev/window-management-on-macos-with-swiftui-4/) — openWindow, Window vs WindowGroup
15. [KeyboardShortcuts](https://github.com/sindresorhus/KeyboardShortcuts) — Global hotkey library
16. [XPC Services (rderik)](https://rderik.com/blog/xpc-services-on-macos-apps-using-swift/) — XPC architecture
17. [Direct Distribution Guide](https://dev.to/kopiro/how-to-correctly-publish-your-mac-apps-outside-of-the-app-store-38a) — Notarization workflow
