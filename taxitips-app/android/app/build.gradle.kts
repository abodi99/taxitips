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
    namespace = "se.taxitips.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Paketnamnet i Google Play och i Firebase (google-services.json). Byts
        // aldrig: en ny id är en ny app i butiken.
        applicationId = "se.taxitips.app"
        // Flutter 3.44: minSdk 24, targetSdk 36 (Google Play kräver minst 35 för
        // nya appar och uppdateringar). Versionen läses ur pubspec.yaml
        // (`version: 1.0.1+2` -> versionName 1.0.1, versionCode 2). Höj
        // byggnumret före varje uppladdning: Play tar aldrig samma versionCode två gånger.
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
            // Uppladdningsnyckeln (android/key.properties + keystore/, aldrig i
            // git). Google Play signerar om med appens signeringsnyckel (Play App
            // Signing). Utan key.properties signeras releasebygget med
            // debugnyckeln -- duger för en test-APK, men Play avvisar det.
            signingConfig = if (keystorePropertiesFile.exists()) {
                signingConfigs.getByName("release")
            } else {
                logger.warn(
                    "VARNING: android/key.properties saknas -- releasebygget signeras " +
                        "med debugnyckeln och kan inte laddas upp till Google Play."
                )
                signingConfigs.getByName("debug")
            }
            // R8 (minify + resurskrympning) slås på av Flutters Gradle-plugin för
            // release. Pluginen och Firebase har egna keep-regler. Symboltabellen
            // för den inbyggda koden följer med appbunten, så att Play Console kan
            // läsa krascher i Flutter-motorn.
            ndk {
                debugSymbolLevel = "SYMBOL_TABLE"
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
