package com.nora.sdr

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.nora.sdr.audio.AudioPlayer
import com.nora.sdr.data.AppSettings
import com.nora.sdr.data.SettingsStore
import com.nora.sdr.net.ConnState
import com.nora.sdr.net.SdrClient
import com.nora.sdr.net.SdrStatus
import com.nora.sdr.ui.WaterfallState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Orchestrates settings, transport, audio playback, and the waterfall. The UI
 * observes [settings], [conn], and [status]; control actions are fire-and-forget
 * and then re-confirmed by the periodic status poll.
 */
class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val tag = "NetworkedSDR"
    private val store = SettingsStore(app)

    val waterfall = WaterfallState()
    private val audio = AudioPlayer()

    private val client = SdrClient(
        onAudioFrame = { audio.submit(it) },
        onSpectrumFrame = { waterfall.push(it) },
        onAudioFormat = { Log.i(tag, "negotiated audio format $it") },
    )

    val conn: StateFlow<ConnState> = client.state

    private val _settings = MutableStateFlow(AppSettings())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    private val _status = MutableStateFlow<SdrStatus?>(null)
    val status: StateFlow<SdrStatus?> = _status.asStateFlow()

    init {
        viewModelScope.launch {
            _settings.value = store.settings.first()
            audio.setVolume(_settings.value.volume)
        }
        // Poll /status once a second while connected.
        viewModelScope.launch {
            while (true) {
                if (conn.value == ConnState.Connected) {
                    client.status()?.let { _status.value = it }
                }
                delay(1000)
            }
        }
    }

    fun connect() {
        val s = _settings.value
        audio.start()
        client.connect(s.host, s.port)
        // Push our persisted radio settings to the server on connect.
        viewModelScope.launch {
            delay(300)
            client.setMode(s.mode)
            client.tune(s.freqHz)
            applyGain(s.gainAuto, s.gainDb)
            client.setSquelch(s.squelchDb.toDouble())
        }
    }

    fun disconnect() {
        client.disconnect()
        audio.stop()
    }

    // ----- control actions (persist + send) -----
    fun setHostPort(host: String, port: Int) = persist { it.copy(host = host, port = port) }

    fun tune(freqHz: Long) {
        persist { it.copy(freqHz = freqHz) }
        viewModelScope.launch { client.tune(freqHz) }
    }

    /** Tap-to-tune: fraction in [-0.5,0.5] of the current span. */
    fun tuneByFraction(frac: Float) {
        val st = _status.value ?: return
        val target = st.centerHz + (frac * st.sampleRate).toLong()
        tune(target)
    }

    fun setMode(mode: String) {
        persist { it.copy(mode = mode) }
        viewModelScope.launch { client.setMode(mode) }
    }

    fun setGain(auto: Boolean, db: Float) {
        persist { it.copy(gainAuto = auto, gainDb = db) }
        applyGain(auto, db)
    }

    private fun applyGain(auto: Boolean, db: Float) {
        viewModelScope.launch { client.setGain(if (auto) null else db.toDouble()) }
    }

    fun setSquelch(db: Float) {
        persist { it.copy(squelchDb = db) }
        viewModelScope.launch { client.setSquelch(db.toDouble()) }
    }

    fun setVolume(v: Float) {
        persist { it.copy(volume = v) }
        audio.setVolume(v)
    }

    private fun persist(transform: (AppSettings) -> AppSettings) {
        val next = transform(_settings.value)
        _settings.value = next
        viewModelScope.launch { store.update(next) }
    }

    override fun onCleared() {
        disconnect()
        super.onCleared()
    }
}
