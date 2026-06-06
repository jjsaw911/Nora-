#!/usr/bin/env python3
"""Minimal /ws/audio test client — plays the PCM stream out the speakers.

    pip install websockets sounddevice
    python tests/audio_client.py ws://localhost:8080/ws/audio

If sounddevice/PortAudio isn't available it writes raw PCM to audio_dump.raw,
which you can play with:  ffplay -f s16le -ar 24000 -ac 1 audio_dump.raw
"""
import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8080/ws/audio"


async def main():
    async with websockets.connect(URL, max_size=None) as ws:
        fmt = json.loads(await ws.recv())
        print("format:", fmt)
        rate = fmt["rate"]
        try:
            import sounddevice as sd

            stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
            stream.start()
            print("playing... Ctrl-C to stop")
            while True:
                stream.write(await ws.recv())
        except ImportError:
            print("sounddevice missing; dumping to audio_dump.raw")
            with open("audio_dump.raw", "wb") as f:
                while True:
                    f.write(await ws.recv())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
