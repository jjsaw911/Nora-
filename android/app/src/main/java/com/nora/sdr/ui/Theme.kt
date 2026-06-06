package com.nora.sdr.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColors = darkColorScheme(
    primary = Color(0xFF4CC9F0),
    secondary = Color(0xFFF72585),
    background = Color(0xFF0B132B),
    surface = Color(0xFF1C2541),
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF0B6E99),
    secondary = Color(0xFFB5179E),
)

@Composable
fun NetworkedSdrTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
