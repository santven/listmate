# Building Listmate for App Stores

Listmate uses [Capacitor](https://capacitorjs.com/) in **server mode** — the native app loads `https://grocerlist.app` in a WebView. Web changes are instantly live; you only rebuild the native apps when you change plugins, icons, permissions, or Capacitor config.

## Prerequisites

| What | Needed for | Cost |
|------|------------|------|
| Mac with Xcode 15+ | iOS builds | $99/yr (Apple Developer) |
| Android Studio | Android builds | $25 one-time (Google Play) |
| Node.js 18+ | Capacitor CLI | Free |

## Initial setup (Mac)

```bash
git clone https://github.com/santven/listmate.git
cd listmate
npm install
npx cap add android
npx cap add ios
```

## App Icons

Replace these files with your branded assets, then run `npx cap sync`:

| File | Size | Purpose |
|------|------|---------|
| `resources/icon.png` | 1024×1024 px | App icon (all platforms) |
| `resources/splash.png` | 2732×2732 px | Splash screen |

## Android — Play Store

```bash
npx cap open android
```

In Android Studio:
1. **Build → Generate Signed Bundle / APK**
2. Choose **Android App Bundle (.aab)**
3. Create a new keystore if you don't have one (save the `.jks` file and password securely!)
4. Build → upload the `.aab` to [Google Play Console](https://play.google.com/console)

**To update after web changes:** Do nothing. Server mode handles it.

**To update after native changes** (plugins, config, icon):
```bash
npx cap sync android
npx cap open android
# Build → Generate Signed Bundle again
```

## iOS — App Store

```bash
npx cap open ios
```

In Xcode:
1. Select the **Listmate** scheme and **Any iOS Device** target
2. Signing & Capabilities → select your Apple Developer team
3. **Product → Archive**
4. In the Organizer window → **Distribute App** → App Store Connect

**Apple Sign-In:** Required by App Store review. Add the Sign In with Apple capability in Xcode → Signing & Capabilities → "+" → Sign In with Apple.

**To update after native changes:**
```bash
npx cap sync ios
npx cap open ios
# Archive again
```

## Debugging

```bash
npx cap doctor          # Check setup health

# Android debugging
npx cap open android    # Opens Studio with full debugging

# iOS debugging
npx cap open ios        # Opens Xcode with Safari Web Inspector
```

## When to rebuild

| Change | Rebuild needed? |
|--------|:--:|
| HTML, CSS, JavaScript changes | ❌ No — instant via server mode |
| Backend API changes | ❌ No — Render deploy |
| New Capacitor plugin added | ✅ Yes — `cap sync` + rebuild |
| App icon, splash screen updated | ✅ Yes — `cap sync` + rebuild |
| Capacitor config changed | ✅ Yes — `cap sync` + rebuild |
| Android permissions added | ✅ Yes — rebuild Android |
| iOS capabilities added | ✅ Yes — rebuild iOS |
