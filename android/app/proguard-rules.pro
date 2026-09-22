# Keep model classes for Gson
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
-keep class com.dropfile.mobile.data.** { *; }
