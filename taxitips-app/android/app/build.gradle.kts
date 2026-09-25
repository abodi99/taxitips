import java.util.Properties

// Google Maps-nyckeln: android/local.properties (MAPS_API_KEY=...) eller miljövariabeln
// MAPS_API_KEY. Aldrig i git. Utan nyckel byggs appen ändå; kartan i appen använder då
// flutter_map (se lib/widgets/google_signal_map.dart och --dart-define=GOOGLE_MAPS=true).
// android/maps.properties går före: Flutter skriver om local.properties vid varje bygge
// och tappade nyckeln en gång (2026-09-25), vilket gav en tom karta.
val mapsApiKey: String = run {
    val props = Properties()
    for (name in listOf("local.properties", "maps.properties")) {
        val file = rootProject.file(name)
        if (file.exists()) file.inputStream().use { props.load(it) }
    }
    props.getProperty("MAPS_API_KEY") ?: System.getenv("MAPS_API_KEY") ?: ""
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystorePropertiesFile.inputStream().use { keystoreProperties.load(it) }
}

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    id("com.google.gms.google-services")
    id("com.google.firebase.crashlytics")
}

android {
    namespace = "se.taxibehov.taxibehov_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "se.taxibehov.taxibehov_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = maxOf(flutter.minSdkVersion, 23)
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        manifestPlaceholders["MAPS_API_KEY"] = mapsApiKey
    }

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = rootProject.file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (keystorePropertiesFile.exists()) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
