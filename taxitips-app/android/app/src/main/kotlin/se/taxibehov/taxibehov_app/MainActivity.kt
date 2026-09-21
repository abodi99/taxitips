package se.taxibehov.taxibehov_app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createTipsChannel()
    }

    /**
     * Kanalen för taxitips, med hög vikt så att notisen dyker upp ovanpå
     * navigationsappen i stället för att läggas tyst i panelen.
     *
     * Id:t måste stämma med manifestets
     * `default_notification_channel_id` och backendens `ANDROID_CHANNEL_ID`
     * (billing/fcm.py). En kanals vikt går inte att höja i efterhand -- Android
     * behåller den första -- så ändras vikten behöver id:t bytas.
     */
    private fun createTipsChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(TIPS_CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            TIPS_CHANNEL_ID,
            "Taxitips",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Nya störningar där det kan finnas kunder."
            enableVibration(true)
        }
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val TIPS_CHANNEL_ID = "taxitips_tips"
    }
}
