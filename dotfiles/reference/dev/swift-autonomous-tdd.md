# Plan: Containerized iOS Development with Claude Code on Mac Mini M4

**Date:** 2026-03-03
**Research:** `RESOURCES/biz/containerized-ios-development-workflow-2026-03-03.md`

---

## Architecture

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│  Docker Container (Linux)       │     │  macOS Host (Mac Mini M4)       │
│                                 │     │                                 │
│  Claude Code                    │SSH  │  xcodebuild / swift build       │
│  Source editing at /workspace   │────▶│  xcrun simctl (simulators)      │
│  Build triggering via SSH       │     │  xcrun devicectl (devices)      │
│  Result parsing (xcsift)        │◀────│  Build results (.xcresult)      │
│                                 │     │  fswatch (optional watcher)     │
└────────────┬────────────────────┘     └────────────┬────────────────────┘
             │                                       │
             └──── Bind mount: /path/to/MyApp ────┘
```

## Implementation Steps

### Phase 1: Host-Side Setup

1. **Enable SSH on Mac Mini**
   - System Settings → General → Sharing → Remote Login
   - Create `builduser` account, add to `_developer` group
   - Set up SSH key auth (no password)

2. **Install host-side tools**
   ```bash
   brew install xcsift xcbeautify fswatch fastlane swiftformat
   ```

3. **Verify xcodebuild works headlessly**
   ```bash
   xcodebuild -scheme MyScheme -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | xcsift
   ```

### Phase 2: Container Setup

4. **Configure Docker container with SSH access**
   - Mount SSH key for host access
   - Mount source code as bind volume
   - Set `host.docker.internal` (or OrbStack equivalent)

5. **Test SSH build triggering from container**
   ```bash
   ssh builduser@host.docker.internal "cd /path/to/MyApp && swift build 2>&1 | xcsift"
   ```

### Phase 3: Build Script Wrapper

6. **Create a build-bridge script** on the host that Claude Code calls via SSH:
   ```bash
   # /usr/local/bin/ios-build
   # Accepts: action (build|test|run), scheme, destination
   # Returns: xcsift-formatted JSON output
   ```

   This script should:
   - Accept action, scheme, and destination as arguments
   - Run xcodebuild with `-resultBundlePath` for full results
   - Pipe output through xcsift for structured JSON
   - Return exit code + structured output

### Phase 4: Testing Integration

7. **Unit tests:** `swift test 2>&1 | xcsift` via SSH
8. **UI tests:** `xcodebuild test` with headless simulator via SSH
9. **Screenshots:** `xcrun simctl io booted screenshot` after test runs
10. **Accessibility:** Install `axe` or `ios-simulator-skill` for UI tree inspection

### Phase 5: Device Deployment

11. **One-time:** Pair iPhone via Xcode GUI
12. **Ongoing:** `xcrun devicectl device install app` + `launch app` via SSH

## Key Decisions Needed

- **Project type:** SwiftPM package (simpler, `swift build/test`) vs Xcode project (need .xcodeproj management)?
- **Project generation:** If Xcode project, use XcodeGen or Tuist so Claude Code edits YAML/Swift config instead of binary .pbxproj?
- **UI framework:** SwiftUI (programmatic, no IB needed) vs UIKit (may need storyboards)?
- **xcsift format:** JSON (standard) vs TOON (30-60% fewer tokens, matters for long sessions)?
- **MCP server:** Use xcsift's MCP server for direct integration, or keep it simple with SSH + pipe?

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| SSH connection drops | Use `autossh` or connection pooling |
| Build output too large for context | xcsift + quiet mode; only surface errors |
| Simulator boot slow | Pre-boot simulators, keep them running |
| Code signing complexity | Use Fastlane `match` for certificate management |
| xcresulttool API changes | xcsift abstracts this; stay on xcsift updates |
| First-time device pairing needs GUI | Document as manual one-time step |
