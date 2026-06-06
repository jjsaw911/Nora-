package com.nora.sdr.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicInteger

/**
 * Streaming PCM playback with a small jitter buffer.
 *
 * Bytes from /ws/audio (s16le mono) are queued and written to an [AudioTrack] on
 * a dedicated thread. Playback only starts once ~[primeMs] of audio is buffered;
 * on underrun we write silence (brief mute) rather than glitch-looping the last
 * buffer. Verbose, greppable logs (tag NetworkedSDR) so the operator can see the
 * pipeline state.
 */
class AudioPlayer(
    private val sampleRate: Int = 24000,
    private val primeMs: Int = 150,
) {
    private val tag = "NetworkedSDR"
    private val bytesPerMs = sampleRate * 2 / 1000   // mono s16
    private val queue = LinkedBlockingQueue<ByteArray>()
    private val buffered = AtomicInteger(0)
    @Volatile private var running = false
    @Volatile private var muted = false
    @Volatile private var volume = 1.0f
    private var track: AudioTrack? = null
    private var thread: Thread? = null

    fun start() {
        if (running) return
        val minBuf = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(bytesPerMs * 100)

        track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(sampleRate)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setBufferSizeInBytes(minBuf * 2)
            .build()
            .also { it.setVolume(volume) }

        running = true
        thread = Thread({ playLoop() }, "sdr-audio").apply { start() }
        Log.i(tag, "AudioPlayer started: rate=$sampleRate primeMs=$primeMs minBuf=$minBuf")
    }

    /** Feed one PCM frame from the WebSocket. */
    fun submit(frame: ByteArray) {
        if (!running) return
        queue.offer(frame)
        buffered.addAndGet(frame.size)
    }

    fun setVolume(v: Float) {
        volume = v.coerceIn(0f, 1f)
        track?.setVolume(volume)
    }

    fun clear() {
        queue.clear()
        buffered.set(0)
    }

    fun stop() {
        running = false
        thread?.interrupt()
        thread = null
        try {
            track?.pause(); track?.flush(); track?.release()
        } catch (e: Exception) {
            Log.w(tag, "AudioPlayer stop error", e)
        }
        track = null
        clear()
        Log.i(tag, "AudioPlayer stopped")
    }

    private fun playLoop() {
        val t = track ?: return
        val silence = ByteArray(bytesPerMs * 20)  // 20 ms of silence
        var primed = false
        t.play()
        while (running) {
            try {
                if (!primed) {
                    if (buffered.get() < primeMs * bytesPerMs) {
                        Thread.sleep(5); continue
                    }
                    primed = true
                    Log.i(tag, "AudioPlayer primed (${buffered.get() / bytesPerMs} ms buffered)")
                }
                val frame = queue.poll()
                if (frame == null) {
                    // Underrun: briefly mute, then re-prime to avoid glitch-loop.
                    if (!muted) Log.w(tag, "AudioPlayer underrun -> muting until re-primed")
                    muted = true
                    primed = false
                    t.write(silence, 0, silence.size)
                } else {
                    if (muted) { Log.i(tag, "AudioPlayer resumed"); muted = false }
                    buffered.addAndGet(-frame.size)
                    t.write(frame, 0, frame.size)
                }
            } catch (e: InterruptedException) {
                break
            } catch (e: Exception) {
                Log.e(tag, "AudioPlayer write error", e)
            }
        }
    }
}
