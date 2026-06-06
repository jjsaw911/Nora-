package com.nora.sdr

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nora.sdr.net.ConnState
import com.nora.sdr.ui.NetworkedSdrTheme
import com.nora.sdr.ui.WaterfallView

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            NetworkedSdrTheme {
                val vm: MainViewModel = viewModel()
                App(vm)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(vm: MainViewModel) {
    var showSettings by remember { mutableStateOf(false) }
    val conn by vm.conn.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (showSettings) "Settings" else "Networked SDR") },
                navigationIcon = {
                    if (showSettings) {
                        TextButton(onClick = { showSettings = false }) { Text("Back") }
                    }
                },
                actions = {
                    ConnDot(conn)
                    if (!showSettings) {
                        TextButton(onClick = { showSettings = true }) { Text("Settings") }
                    }
                },
            )
        }
    ) { pad ->
        if (showSettings) {
            SettingsScreen(vm, Modifier.padding(pad))
        } else {
            MainScreen(vm, Modifier.padding(pad))
        }
    }
}

@Composable
private fun ConnDot(conn: ConnState) {
    val (label, color) = when (conn) {
        ConnState.Connected -> "connected" to Color(0xFF4CAF50)
        ConnState.Connecting -> "connecting" to Color(0xFFFFC107)
        ConnState.Reconnecting -> "reconnecting" to Color(0xFFFFC107)
        ConnState.Error -> "error" to Color(0xFFF44336)
        ConnState.Disconnected -> "offline" to Color(0xFF9E9E9E)
    }
    Text(label, color = color, modifier = Modifier.padding(end = 8.dp))
}

@Composable
fun MainScreen(vm: MainViewModel, modifier: Modifier = Modifier) {
    val settings by vm.settings.collectAsState()
    val status by vm.status.collectAsState()
    val conn by vm.conn.collectAsState()

    var freqText by remember(settings.freqHz) { mutableStateOf("%.3f".format(settings.freqHz / 1e6)) }

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Connect / disconnect
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (conn == ConnState.Disconnected || conn == ConnState.Error) {
                Button(onClick = { vm.connect() }) { Text("Connect") }
            } else {
                OutlinedButton(onClick = { vm.disconnect() }) { Text("Disconnect") }
            }
            Spacer(Modifier.width(12.dp))
            status?.let {
                Text("signal ${"%.0f".format(it.signalDb)} dB" + if (it.mock == true) " (mock)" else "")
            }
        }

        // Frequency
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = freqText,
                onValueChange = { freqText = it },
                label = { Text("Frequency (MHz)") },
                singleLine = true,
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = KeyboardType.Decimal
                ),
                modifier = Modifier.width(200.dp),
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = {
                freqText.toDoubleOrNull()?.let { vm.tune((it * 1e6).toLong()) }
            }) { Text("Tune") }
        }
        status?.let { Text("Tuned: ${"%.3f".format(it.centerHz / 1e6)} MHz  •  span ${"%.2f".format(it.sampleRate / 1e6)} MHz") }

        // Mode
        Text("Mode", style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("wbfm", "nbfm", "am").forEach { m ->
                FilterChip(
                    selected = settings.mode == m,
                    onClick = { vm.setMode(m) },
                    label = { Text(m.uppercase()) },
                )
            }
        }

        // Gain
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Gain ${if (settings.gainAuto) "auto" else "%.0f dB".format(settings.gainDb)}")
            Spacer(Modifier.width(12.dp))
            Text("Auto")
            Switch(checked = settings.gainAuto, onCheckedChange = { vm.setGain(it, settings.gainDb) })
        }
        if (!settings.gainAuto) {
            Slider(
                value = settings.gainDb,
                onValueChange = { vm.setGain(false, it) },
                valueRange = 0f..49f,
            )
        }

        // Squelch
        Text("Squelch ${"%.0f".format(settings.squelchDb)} dB")
        Slider(
            value = settings.squelchDb,
            onValueChange = { vm.setSquelch(it) },
            valueRange = -90f..0f,
        )

        // Volume
        Text("Volume ${"%.0f".format(settings.volume * 100)}%")
        Slider(
            value = settings.volume,
            onValueChange = { vm.setVolume(it) },
            valueRange = 0f..1f,
        )

        // Waterfall + spectrum (tap to tune)
        Text("Spectrum (tap to tune)", style = MaterialTheme.typography.labelLarge)
        WaterfallView(
            state = vm.waterfall,
            modifier = Modifier
                .fillMaxWidth()
                .height(360.dp),
            onTapFraction = { vm.tuneByFraction(it) },
        )
    }
}

@Composable
fun SettingsScreen(vm: MainViewModel, modifier: Modifier = Modifier) {
    val settings by vm.settings.collectAsState()
    var host by remember(settings.host) { mutableStateOf(settings.host) }
    var port by remember(settings.port) { mutableStateOf(settings.port.toString()) }

    Column(
        modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Raspberry Pi connection", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text("Host / IP") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = port,
            onValueChange = { port = it.filter(Char::isDigit) },
            label = { Text("Port") },
            singleLine = true,
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                keyboardType = KeyboardType.Number
            ),
            modifier = Modifier.width(160.dp),
        )
        Button(onClick = {
            vm.setHostPort(host.trim(), port.toIntOrNull() ?: 8080)
        }) { Text("Save") }
        Text(
            "The Pi server owns the SDR and streams audio + spectrum. " +
                "Default port 8080.",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
