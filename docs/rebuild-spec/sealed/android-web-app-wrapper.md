# Sealed notes: android-web-app-wrapper

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 2 notes.

### DSH-S01: Android hid the address bar only for a verified site.
- Why: An Android web-app wrapper hides the bar only if the site publishes a statement naming the app and its signing key fingerprint; otherwise it silently falls back.
- Must: The site publishes that statement, allows two signing keys during a hand-over, and a check reports whether it verifies.
- Tool: Android Trusted Web Activity (Digital Asset Links)
- Where it bit: The dashboard

### REL-S08: Building the Android app wrapper failed with unhelpful errors.
- Why: The builder demands a file from a retired Android SDK package, and the resource linker rejects a package name part starting with an underscore.
- Must: The Android app builds from a clean machine in one step, with a package name every Android tool accepts.
- Tool: Bubblewrap (TWA builder) and aapt2
- Where it bit: Releases and updates
