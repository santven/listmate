# Walkthrough - Support for Android API 36

I have upgraded the project's build configuration to support Android API 36, which was required by several `androidx` dependencies.

## Changes Made

### Build Configuration

- **`variables.gradle`**: Updated `compileSdkVersion` and `targetSdkVersion` to `36`.
- **Root `build.gradle`**: Upgraded Android Gradle Plugin to `8.9.1`.
- **`gradle-wrapper.properties`**: Upgraded Gradle distribution to `8.12.1` to support the new AGP version.

## Verification Results

### Automated Tests
- **Gradle Sync**: Completed successfully, ensuring the IDE is correctly configured with the new SDK.
- **Build**: Executed `./gradlew :app:assembleDebug` successfully. This confirms that the AAR metadata dependency errors (which previously blocked the build) are resolved.

> [!IMPORTANT]
> If you encounter issues running the app, ensure you have the **Android 16 (API 36)** SDK components installed via the Android Studio SDK Manager.
