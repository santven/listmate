# Implementation Plan - Fix Android App Icon

The app is currently showing the default Android placeholder icon. This is likely due to the adaptive icon configuration in `mipmap-anydpi-v26` pointing to placeholder/default resources, and the intended branding assets in `icon-override/` not being correctly applied to the Android project.

## User Review Required

> [!IMPORTANT]
> This plan will overwrite existing icon files in `android/app/src/main/res/mipmap-*` with those found in `icon-override/`. It will also change the adaptive icon background to a solid white color as defined in `res/values/ic_launcher_background.xml`.

## Proposed Changes

### Android Resources

#### [MODIFY] [ic_launcher.xml](file:///Users/venkatsanthanam/Downloads/listmate-main-aug-15-2/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml)
- Update the background layer to use `@color/ic_launcher_background` (white) instead of `@mipmap/ic_launcher_background`.
- Remove the `inset` from the background layer as it's not needed for a solid color.

#### [MODIFY] [ic_launcher_round.xml](file:///Users/venkatsanthanam/Downloads/listmate-main-aug-15-2/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml)
- Similar update to use the color background.

#### [DELETE] [ic_launcher_background.png](file:///Users/venkatsanthanam/Downloads/listmate-main-aug-15-2/android/app/src/main/res/mipmap-*)
- Remove all `ic_launcher_background.png` files from the density-specific mipmap folders to ensure the system doesn't accidentally pick them up over the color resource.

#### [MODIFY] [App Icons](file:///Users/venkatsanthanam/Downloads/listmate-main-aug-15-2/android/app/src/main/res/mipmap-*)
- Copy/Overwrite the following files from `icon-override/` to all matching density folders in `android/app/src/main/res/`:
    - `ic_launcher.png`
    - `ic_launcher_round.png`
    - `ic_launcher_foreground.png`

## Verification Plan

### Automated Tests
- Run `./gradlew assembleDebug` to verify that the resource changes don't break the build.

### Manual Verification
- Deploy to an Android device or emulator.
- Verify that the app icon correctly displays the Listmate brand with a white background.
