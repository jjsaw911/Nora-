package com.nora.sdr.ui

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput

const val SPECTRUM_BINS = 1024

/** 256-entry blue→cyan→green→yellow→red palette for power bytes. */
object Palette {
    val table: IntArray = IntArray(256) { v ->
        val t = v / 255f
        val r = ((t - 0.5f) * 2f).coerceIn(0f, 1f)
        val g = (1f - kotlin.math.abs(t - 0.5f) * 2f).coerceIn(0f, 1f)
        val b = ((0.5f - t) * 2f).coerceIn(0f, 1f)
        (0xFF shl 24) or
            ((r * 255).toInt() shl 16) or
            ((g * 255).toInt() shl 8) or
            (b * 255).toInt()
    }
}

/**
 * Holds the scrolling waterfall image. Each [push] adds a new row at the top and
 * scrolls the rest down. Backed by an IntArray pixel store for cheap scrolling.
 */
class WaterfallState(
    val width: Int = SPECTRUM_BINS,
    val height: Int = 320,
) {
    val bitmap: Bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    private val pixels = IntArray(width * height)
    var latest: ByteArray = ByteArray(width)
        private set

    // Bumped on each frame so Compose recomposes.
    var version by mutableIntStateOf(0)
        private set

    fun push(frame: ByteArray) {
        if (frame.size != width) return
        // Scroll everything down one row.
        System.arraycopy(pixels, 0, pixels, width, width * (height - 1))
        // New top row from the palette.
        for (x in 0 until width) {
            pixels[x] = Palette.table[frame[x].toInt() and 0xFF]
        }
        bitmap.setPixels(pixels, 0, width, 0, 0, width, height)
        latest = frame
        version++
    }
}

/**
 * Draws the spectrum line on top and the scrolling waterfall below. Tapping
 * anywhere reports the horizontal position as a fraction in [-0.5, 0.5] of the
 * span (for tap-to-tune).
 */
@Composable
fun WaterfallView(
    state: WaterfallState,
    modifier: Modifier = Modifier,
    spectrumFraction: Float = 0.28f,
    onTapFraction: (Float) -> Unit = {},
) {
    val version = state.version  // read so we recompose on new frames
    Canvas(
        modifier = modifier.pointerInput(Unit) {
            detectTapGestures { offset ->
                val frac = (offset.x / size.width) - 0.5f
                onTapFraction(frac.coerceIn(-0.5f, 0.5f))
            }
        }
    ) {
        @Suppress("UNUSED_EXPRESSION") version
        val specH = size.height * spectrumFraction
        val wfTop = specH
        val wfH = size.height - specH

        // Waterfall image scaled to fill the lower region.
        drawImage(
            image = state.bitmap.asImageBitmap(),
            dstOffset = androidx.compose.ui.unit.IntOffset(0, wfTop.toInt()),
            dstSize = androidx.compose.ui.unit.IntSize(size.width.toInt(), wfH.toInt()),
        )
        drawSpectrumLine(state.latest, specH)
    }
}

private fun DrawScope.drawSpectrumLine(frame: ByteArray, height: Float) {
    if (frame.isEmpty()) return
    val w = size.width
    val n = frame.size
    val path = Path()
    for (i in 0 until n) {
        val x = i / (n - 1f) * w
        val v = (frame[i].toInt() and 0xFF) / 255f
        val y = height - v * height
        if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    drawPath(path, color = Color(0xFF4CC9F0), style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2f))
}
