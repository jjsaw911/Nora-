package com.nora.sdr.net

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

enum class ConnState { Disconnected, Connecting, Connected, Reconnecting, Error }

data class SdrStatus(
    val centerHz: Long,
    val mode: String,
    val gainDb: String,      // numeric string or "auto"
    val sampleRate: Int,
    val audioRate: Int,
    val squelchDb: Double,
    val running: Boolean,
    val signalDb: Double,
    val mock: Boolean?,
)

/**
 * Thin-client transport: REST control plane + audio/spectrum WebSockets.
 *
 * Both sockets auto-reconnect with exponential backoff (capped). The overall
 * [state] tracks the audio socket (the primary stream); the spectrum socket
 * reconnects independently. All control calls are suspend functions on IO.
 */
class SdrClient(
    private val onAudioFrame: (ByteArray) -> Unit,
    private val onSpectrumFrame: (ByteArray) -> Unit,
    private val onAudioFormat: (JSONObject) -> Unit = {},
) {
    private val tag = "NetworkedSDR"
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // long-lived sockets
        .build()

    private val jsonMedia = "application/json".toMediaType()

    @Volatile private var host: String = ""
    @Volatile private var port: Int = 8080
    @Volatile private var wanted = false
    private var audioWs: WebSocket? = null
    private var spectrumWs: WebSocket? = null

    private val _state = MutableStateFlow(ConnState.Disconnected)
    val state: StateFlow<ConnState> = _state.asStateFlow()

    private fun httpBase() = "http://$host:$port"
    private fun wsBase() = "ws://$host:$port"

    fun connect(host: String, port: Int) {
        this.host = host
        this.port = port
        wanted = true
        _state.value = ConnState.Connecting
        Log.i(tag, "connect -> ${httpBase()}")
        openAudio(0)
        openSpectrum(0)
    }

    fun disconnect() {
        wanted = false
        audioWs?.close(1000, "bye"); audioWs = null
        spectrumWs?.close(1000, "bye"); spectrumWs = null
        _state.value = ConnState.Disconnected
        Log.i(tag, "disconnected")
    }

    // --------------------------------------------------------------- REST
    suspend fun status(): SdrStatus? = getJson("/status")?.let {
        SdrStatus(
            centerHz = it.optLong("center_hz"),
            mode = it.optString("mode"),
            gainDb = it.opt("gain_db")?.toString() ?: "auto",
            sampleRate = it.optInt("sample_rate"),
            audioRate = it.optInt("audio_rate"),
            squelchDb = it.optDouble("squelch_db", -40.0),
            running = it.optBoolean("running"),
            signalDb = it.optDouble("signal_db", -120.0),
            mock = if (it.isNull("mock")) null else it.optBoolean("mock"),
        )
    }

    suspend fun config(): JSONObject? = getJson("/config")

    suspend fun tune(freqHz: Long) = postJson("/tune", JSONObject().put("freq_hz", freqHz))
    suspend fun setMode(mode: String) = postJson("/mode", JSONObject().put("mode", mode))
    suspend fun setSquelch(db: Double) = postJson("/squelch", JSONObject().put("db", db))
    suspend fun setGain(db: Double?) = postJson(
        "/gain",
        JSONObject().put("gain_db", if (db == null) "auto" else db),
    )

    private suspend fun getJson(path: String): JSONObject? = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(httpBase() + path).build()).execute().use { r ->
                if (!r.isSuccessful) return@use null
                r.body?.string()?.let { JSONObject(it) }
            }
        }.onFailure { Log.w(tag, "GET $path failed: ${it.message}") }.getOrNull()
    }

    private suspend fun postJson(path: String, body: JSONObject): Boolean =
        withContext(Dispatchers.IO) {
            runCatching {
                val req = Request.Builder()
                    .url(httpBase() + path)
                    .post(body.toString().toRequestBody(jsonMedia))
                    .build()
                http.newCall(req).execute().use { it.isSuccessful }
            }.onFailure { Log.w(tag, "POST $path failed: ${it.message}") }.getOrDefault(false)
        }

    // ----------------------------------------------------------- sockets
    private fun backoff(attempt: Int): Long =
        (1000L * (1 shl attempt.coerceAtMost(4))).coerceAtMost(16_000L)

    private fun openAudio(attempt: Int) {
        if (!wanted) return
        val req = Request.Builder().url(wsBase() + "/ws/audio").build()
        audioWs = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(tag, "audio ws open")
                _state.value = ConnState.Connected
            }

            override fun onMessage(ws: WebSocket, text: String) {
                // First message is the format descriptor.
                runCatching { onAudioFormat(JSONObject(text)) }
                Log.i(tag, "audio format: $text")
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                onAudioFrame(bytes.toByteArray())
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                Log.i(tag, "audio ws closed: $code $reason")
                scheduleReopen(attempt, ::openAudio, "audio")
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.w(tag, "audio ws failure: ${t.message}")
                scheduleReopen(attempt, ::openAudio, "audio")
            }
        })
    }

    private fun openSpectrum(attempt: Int) {
        if (!wanted) return
        val req = Request.Builder().url(wsBase() + "/ws/spectrum").build()
        spectrumWs = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(tag, "spectrum ws open")
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                onSpectrumFrame(bytes.toByteArray())
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                scheduleReopen(attempt, ::openSpectrum, "spectrum")
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.w(tag, "spectrum ws failure: ${t.message}")
                scheduleReopen(attempt, ::openSpectrum, "spectrum")
            }
        })
    }

    private fun scheduleReopen(attempt: Int, open: (Int) -> Unit, which: String) {
        if (!wanted) return
        if (which == "audio") _state.value = ConnState.Reconnecting
        val wait = backoff(attempt)
        Log.i(tag, "reconnecting $which in ${wait}ms (attempt ${attempt + 1})")
        scope.launch {
            delay(wait)
            if (wanted) open(attempt + 1)
        }
    }
}
