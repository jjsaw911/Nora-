package com.nora.sdr.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Persisted connection + last-used radio settings (M6). */
data class AppSettings(
    val host: String = "192.168.1.10",
    val port: Int = 8080,
    val freqHz: Long = 96_900_000,
    val mode: String = "wbfm",
    val gainDb: Float = 30f,       // -1 == auto
    val gainAuto: Boolean = true,
    val squelchDb: Float = -40f,
    val volume: Float = 0.8f,
)

private val Context.dataStore by preferencesDataStore(name = "sdr_settings")

class SettingsStore(private val context: Context) {
    private object Keys {
        val HOST = stringPreferencesKey("host")
        val PORT = intPreferencesKey("port")
        val FREQ = longPreferencesKey("freq")
        val MODE = stringPreferencesKey("mode")
        val GAIN = floatPreferencesKey("gain")
        val GAIN_AUTO = intPreferencesKey("gain_auto")
        val SQUELCH = floatPreferencesKey("squelch")
        val VOLUME = floatPreferencesKey("volume")
    }

    val settings: Flow<AppSettings> = context.dataStore.data.map { p ->
        val d = AppSettings()
        AppSettings(
            host = p[Keys.HOST] ?: d.host,
            port = p[Keys.PORT] ?: d.port,
            freqHz = p[Keys.FREQ] ?: d.freqHz,
            mode = p[Keys.MODE] ?: d.mode,
            gainDb = p[Keys.GAIN] ?: d.gainDb,
            gainAuto = (p[Keys.GAIN_AUTO] ?: 1) != 0,
            squelchDb = p[Keys.SQUELCH] ?: d.squelchDb,
            volume = p[Keys.VOLUME] ?: d.volume,
        )
    }

    suspend fun update(s: AppSettings) {
        context.dataStore.edit { p ->
            p[Keys.HOST] = s.host
            p[Keys.PORT] = s.port
            p[Keys.FREQ] = s.freqHz
            p[Keys.MODE] = s.mode
            p[Keys.GAIN] = s.gainDb
            p[Keys.GAIN_AUTO] = if (s.gainAuto) 1 else 0
            p[Keys.SQUELCH] = s.squelchDb
            p[Keys.VOLUME] = s.volume
        }
    }
}
