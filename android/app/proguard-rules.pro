# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.

# CapAwesome Firebase Authentication (suppress missing optional provider SDK warnings)
-dontwarn com.facebook.**
-dontwarn com.twitter.sdk.android.**
-dontwarn com.google.android.gms.games.**
-dontwarn com.google.android.play.core.**
-dontwarn io.capawesome.capacitorjs.plugins.firebase.authentication.**
-keep class io.capawesome.capacitorjs.plugins.firebase.authentication.** { *; }

# Capacitor plugins
-keep public class * extends com.getcapacitor.Plugin
-keepclassmembers class * extends com.getcapacitor.Plugin {
    @com.getcapacitor.PluginMethod public *;
}

# Firebase and Google
-dontwarn com.google.android.gms.**
-dontwarn com.google.firebase.**
-keepattributes *Annotation*
