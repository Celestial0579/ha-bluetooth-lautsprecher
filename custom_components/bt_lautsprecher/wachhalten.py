"""Hält einen Lautsprecher wach, indem ein unhörbarer Strom an ihn geht."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Callable
from asyncio.subprocess import DEVNULL, PIPE

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PULSE_SOCKET = "/run/audio/pulse.sock"


def wachhalten_moeglich() -> bool:
    """Gibt es PulseAudio (Home Assistant OS) und ffmpeg?"""
    return os.path.exists(PULSE_SOCKET) and shutil.which("ffmpeg") is not None


def senke(adresse: str) -> str:
    """PulseAudio-Ausgabe eines Bluetooth-Geräts."""
    return f"bluez_sink.{adresse.replace(':', '_').upper()}.a2dp_sink"


class Wachhalter:
    """Schickt Stille (oder sehr leises Rauschen) an die Bluetooth-Ausgabe."""

    def __init__(
        self, hass: HomeAssistant, adresse: str, name: str, rauschen: bool,
        bei_aenderung: Callable[[], None] | None = None,
    ) -> None:
        self._hass = hass
        self._adresse = adresse
        self._name = name
        self._rauschen = rauschen
        self._bei_aenderung = bei_aenderung or (lambda: None)
        self._soll = False
        self._aufgabe: asyncio.Task | None = None
        self._prozess: asyncio.subprocess.Process | None = None

    @property
    def laeuft(self) -> bool:
        return self._prozess is not None and self._prozess.returncode is None

    def start(self) -> None:
        if self._aufgabe is not None:
            return
        self._soll = True
        self._aufgabe = self._hass.async_create_background_task(
            self._schleife(), f"bt_lautsprecher_wach_{self._adresse}"
        )

    async def stop(self) -> None:
        self._soll = False
        prozess = self._prozess
        if prozess is not None and prozess.returncode is None:
            prozess.terminate()
            try:
                async with asyncio.timeout(5):
                    await prozess.wait()
            except TimeoutError:
                prozess.kill()
        if self._aufgabe is not None:
            self._aufgabe.cancel()
            self._aufgabe = None

    async def _schleife(self) -> None:
        quelle = "anoisesrc=r=44100:c=pink:a=0.0003" if self._rauschen else "anullsrc=r=44100:cl=stereo"
        befehl = [
            shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-loglevel", "error",
            "-f", "lavfi", "-i", quelle, "-ac", "2",
            "-f", "pulse", "-device", senke(self._adresse), "-name", "bt_lautsprecher",
            f"Wach halten {self._name}",
        ]
        umgebung = {**os.environ, "PULSE_SERVER": f"unix:{PULSE_SOCKET}"}
        while self._soll:
            try:
                self._prozess = await asyncio.create_subprocess_exec(
                    *befehl, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE, env=umgebung
                )
                self._bei_aenderung()
                _, fehler = await self._prozess.communicate()
                if self._soll and fehler:
                    _LOGGER.debug("Wachhalten für %s beendet: %s", self._name, fehler.decode(errors="replace").strip())
            except OSError as err:
                _LOGGER.warning("Wachhalten für %s nicht startbar: %s", self._name, err)
            finally:
                self._prozess = None
                self._bei_aenderung()
            if self._soll:
                await asyncio.sleep(5)
