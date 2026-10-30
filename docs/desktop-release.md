# Desktop packaging and release

The public preview distributes source and the unpacked companion. Native installers are a separate qualification track.

## Build locally

Install Node.js 22.12+, Python 3.11+, Rust and the Tauri platform prerequisites. Initialize `engine/.venv` and install `engine[dev]`, then:

```bash
npm ci
npm run build:desktop
npm run smoke:engine-sidecar -- --port 8877
npm run smoke:desktop
```

The macOS outputs are under `src-tauri/target/release/bundle/macos/` and `bundle/dmg/`. Generated artifacts are ignored. `.env.local` can override the default loopback engine port; build public artifacts with an explicit intended configuration, not a developer's accidental override.

Without `APPLE_SIGNING_IDENTITY`, the wrapper builds an ad-hoc development app. Such a build is not a notarized public installer. Do not recommend bypassing OS security warnings.

## Signed macOS release

The existing `.github/workflows/desktop-release.yml` has validation and signed-release lanes. The signed lane uses the protected `desktop-release` environment and needs a Developer ID certificate, notarization credentials, and updater signing inputs. Keep all private material in a protected secret store.

Required secret names are `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `KEYCHAIN_PASSWORD`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`, `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, and `LORASUITE_UPDATER_PUBLIC_KEY`. The public key is compiled into the updater; private keys must never ship. `APPLE_SIGNING_IDENTITY` must identify the same Team ID for the Python sidecar and outer app.

Before publishing an installer:

1. Pass frontend, companion, engine and Rust tests and production builds.
2. Build the sidecar and native app from the reviewed commit.
3. Verify signatures, hardened runtime, notarization/stapling and Gatekeeper assessment.
4. Exercise clean-machine install, first launch, restart, recovery and uninstall.
5. Verify the actual signed updater archive and manifests; exercise upgrade and rollback when a previous candidate exists.
6. Review the bundle's dependency licenses and notices.
7. Publish accurate platform/model/provider limitations and artifact checksums.

The lifecycle smoke (`npm run smoke:desktop:lifecycle`) starts and stops a test app and refuses to use an occupied engine port. Do not run it against an active user's engine. Static smoke may run while another app is active.

Windows/Linux packaging workflows are manual until their native install and runtime behavior is qualified. Unsigned CI artifacts are not public release installers.
