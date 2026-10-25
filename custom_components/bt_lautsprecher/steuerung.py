"""Ablaufsteuerung: verbindet BlueZ, Einstellungen und Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .bluez import BluetoothError, BluezVerwalter, geraetename, ist_audio
from .const import (
    CONF_ADAPTER,
    CONF_AUTO_RECONNECT,
    CONF_DEFAULT_OUTPUT,
    CONF_KEEPALIVE_NOISE,
    DISCOVERY_SECONDS,
    DOMAIN,
    RECONNECT_INTERVAL_SECONDS,
    SIGNAL_NEW_DEVICES,
    SIGNAL_UPDATE,
)
from .supervisor import standard_ausgabe_setzen
from .wachhalten import Wachhalter, wachhalten_moeglich

_LOGGER = logging.getLogger(__name__)


class Steuerung:
    """Eine Instanz je Bluetooth-Adapter."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.bluez = BluezVerwalter(entry.data[CONF_ADAPTER])
        self.signal = SIGNAL_UPDATE.format(entry.entry_id)
        self.signal_neu = SIGNAL_NEW_DEVICES.format(entry.entry_id)
        self.status = "Bereit"
        self.neu_auswahl: str | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._einstellungen: dict[str, dict[str, bool]] = {}
        self._lock = asyncio.Lock()
        self._gekoppelt: set[str] = set()
        self._verbunden: set[str] = set()
        self._wachhalter: dict[str, Wachhalter] = {}
        self._abmelden: list = []
        self.adapter_geraet_id: str | None = None

    # ------------------------------------------------------------ Abfragen
    def gekoppelte(self) -> dict[str, tuple[str, dict[str, Any]]]:
        """Gekoppelte Audiogeräte als {Adresse: (Pfad, Eigenschaften)}."""
        return {
            str(g.get("Address")): (pfad, g)
            for pfad, g in self.bluez.geraete.items()
            if g.get("Paired") and ist_audio(g)
        }

    def gefundene(self) -> dict[str, dict[str, Any]]:
        """Gefundene, noch nicht gekoppelte Audiogeräte als {Pfad: Eigenschaften}."""
        return {p: g for p, g in self.bluez.geraete.items() if not g.get("Paired") and ist_audio(g)}

    def name(self, adresse: str) -> str:
        eintrag = self.gekoppelte().get(adresse)
        return geraetename(eintrag[1]) if eintrag else adresse

    def ist_verbunden(self, adresse: str) -> bool:
        eintrag = self.gekoppelte().get(adresse)
        return bool(eintrag and eintrag[1].get("Connected"))

    def wach(self, adresse: str) -> bool:
        return self._einstellungen.get(adresse, {}).get("wach", True)

    def wach_aktiv(self, adresse: str) -> bool:
        halter = self._wachhalter.get(adresse)
        return bool(halter and halter.laeuft)

    # ------------------------------------------------------------ Lebenszyklus
    async def async_start(self) -> None:
        await self.bluez.start()
        kennung = str(self.entry.unique_id)
        self.adapter_geraet_id = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, kennung)},
            connections={(dr.CONNECTION_BLUETOOTH, kennung)},
            name="Bluetooth-Lautsprecher",
            manufacturer="BlueZ",
            model=f"Adapter {self.bluez.adapter_pfad.rsplit('/', 1)[-1]}",
        ).id
        daten = await self._store.async_load() or {}
        self._einstellungen = daten.get("geraete", {})
        gekoppelt = self.gekoppelte()
        self._gekoppelt = set(gekoppelt)
        self._verbunden = {a for a, (_p, g) in gekoppelt.items() if g.get("Connected")}
        self._veraltete_geraete_entfernen()
        self._abmelden.append(self.bluez.zuhoerer_hinzufuegen(self._aenderung))
        self._abmelden.append(
            async_track_time_interval(
                self.hass, self._wiederverbinden, timedelta(seconds=RECONNECT_INTERVAL_SECONDS)
            )
        )
        for adresse in self._verbunden:
            self._nach_verbindung(adresse, still=True)

    async def async_stop(self) -> None:
        for abmelden in self._abmelden:
            abmelden()
        self._abmelden.clear()
        for halter in list(self._wachhalter.values()):
            await halter.stop()
        self._wachhalter.clear()
        await self.bluez.stop()

    # ------------------------------------------------------------ Aktionen
    async def async_suchen(self) -> None:
        if self.bluez.suche_laeuft:
            return
        self._status(f"Suche läuft ({DISCOVERY_SECONDS} s) …")
        self.hass.async_create_background_task(self._suche(), f"{DOMAIN}_suche")

    async def _suche(self) -> None:
        try:
            await self.bluez.suchen(DISCOVERY_SECONDS)
        except BluetoothError as err:
            self._status(f"Suche fehlgeschlagen: {err}")
            return
        anzahl = len(self.gefundene())
        self._status(f"Suche beendet: {anzahl} neue Lautsprecher gefunden" if anzahl != 1 else "Suche beendet: 1 neuer Lautsprecher gefunden")

    async def async_koppeln(self) -> None:
        pfad = self.neu_auswahl
        if not pfad or pfad not in self.bluez.geraete:
            raise HomeAssistantError("Bitte zuerst unter „Neues Gerät“ einen Lautsprecher auswählen.")
        geraet = self.bluez.geraete[pfad]
        name = geraetename(geraet)
        adresse = str(geraet.get("Address"))
        self._einstellungen.setdefault(adresse, {"wach": True, "manuell_getrennt": False})
        self._speichern()
        await self._ausfuehren(f"Kopple {name} …", f"Koppeln von {name} fehlgeschlagen", self.bluez.verbinden(pfad))

    async def async_verbinden(self, adresse: str) -> None:
        pfad = self._pfad(adresse)
        self._einstellung(adresse)["manuell_getrennt"] = False
        self._speichern()
        await self._ausfuehren(f"Verbinde {self.name(adresse)} …", f"Verbinden mit {self.name(adresse)} fehlgeschlagen", self.bluez.verbinden(pfad))

    async def async_trennen(self, adresse: str) -> None:
        pfad = self._pfad(adresse)
        self._einstellung(adresse)["manuell_getrennt"] = True
        self._speichern()
        await self._wach_stoppen(adresse)
        await self._ausfuehren(f"Trenne {self.name(adresse)} …", f"Trennen von {self.name(adresse)} fehlgeschlagen", self.bluez.trennen(pfad))

    async def async_wach_setzen(self, adresse: str, an: bool) -> None:
        self._einstellung(adresse)["wach"] = an
        self._speichern()
        if an and self.ist_verbunden(adresse):
            self._wach_starten(adresse)
        elif not an:
            await self._wach_stoppen(adresse)
        self._melden()

    async def async_vergessen(self, adresse: str) -> None:
        pfad = self._pfad(adresse)
        name = self.name(adresse)
        await self._wach_stoppen(adresse)
        await self._ausfuehren(f"Vergesse {name} …", f"Vergessen von {name} fehlgeschlagen", self.bluez.vergessen(pfad))
        self._status(f"{name} vergessen")

    # ------------------------------------------------------------ intern
    async def _ausfuehren(self, vorher: str, fehlertext: str, aufruf) -> None:
        async with self._lock:
            self._status(vorher)
            try:
                await aufruf
            except BluetoothError as err:
                self._status(f"{fehlertext}: {err}")
                raise HomeAssistantError(f"{fehlertext}: {err}") from err

    def _pfad(self, adresse: str) -> str:
        eintrag = self.gekoppelte().get(adresse)
        if eintrag is None:
            raise HomeAssistantError(f"{adresse} ist nicht gekoppelt.")
        return eintrag[0]

    def _einstellung(self, adresse: str) -> dict[str, bool]:
        return self._einstellungen.setdefault(adresse, {"wach": True, "manuell_getrennt": False})

    def _speichern(self) -> None:
        self._store.async_delay_save(lambda: {"geraete": self._einstellungen}, 2)

    def _status(self, text: str) -> None:
        self.status = text[:250]
        self._melden()

    @callback
    def _melden(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _aenderung(self) -> None:
        gekoppelt = self.gekoppelte()
        neu = set(gekoppelt) - self._gekoppelt
        weg = self._gekoppelt - set(gekoppelt)
        self._gekoppelt = set(gekoppelt)
        if neu:
            async_dispatcher_send(self.hass, self.signal_neu, sorted(neu))
        for adresse in weg:
            self._geraet_entfernt(adresse)
        verbunden = {a for a, (_p, g) in gekoppelt.items() if g.get("Connected")}
        for adresse in verbunden - self._verbunden:
            self._nach_verbindung(adresse)
        for adresse in self._verbunden - verbunden:
            self._nach_trennung(adresse)
        self._verbunden = verbunden
        if self.neu_auswahl and self.neu_auswahl not in self.gefundene():
            self.neu_auswahl = None
        self._melden()

    def _nach_verbindung(self, adresse: str, still: bool = False) -> None:
        if not still:
            self.status = f"Verbunden mit {self.name(adresse)}"
        self._einstellung(adresse)["manuell_getrennt"] = False
        self._speichern()
        if self.entry.options.get(CONF_DEFAULT_OUTPUT, True):
            self.hass.async_create_background_task(
                standard_ausgabe_setzen(async_get_clientsession(self.hass), adresse),
                f"{DOMAIN}_ausgabe_{adresse}",
            )
        if self.wach(adresse):
            self._wach_starten(adresse)

    def _nach_trennung(self, adresse: str) -> None:
        self.status = f"Getrennt: {self.name(adresse)}"
        halter = self._wachhalter.pop(adresse, None)
        if halter is not None:
            self.hass.async_create_background_task(halter.stop(), f"{DOMAIN}_wach_stop_{adresse}")

    def _wach_starten(self, adresse: str) -> None:
        if adresse in self._wachhalter:
            return
        if not wachhalten_moeglich():
            self.status = "Wach halten nicht möglich: kein Audio-Plugin (nur Home Assistant OS) oder kein ffmpeg"
            return
        halter = Wachhalter(
            self.hass, adresse, self.name(adresse), self.entry.options.get(CONF_KEEPALIVE_NOISE, False),
            self._melden,
        )
        self._wachhalter[adresse] = halter
        halter.start()

    async def _wach_stoppen(self, adresse: str) -> None:
        halter = self._wachhalter.pop(adresse, None)
        if halter is not None:
            await halter.stop()

    def _geraet_entfernt(self, adresse: str) -> None:
        halter = self._wachhalter.pop(adresse, None)
        if halter is not None:
            self.hass.async_create_background_task(halter.stop(), f"{DOMAIN}_wach_stop_{adresse}")
        self._einstellungen.pop(adresse, None)
        self._speichern()
        registry = dr.async_get(self.hass)
        if (geraet := registry.async_get_device(identifiers={(DOMAIN, adresse)})) is not None:
            registry.async_remove_device(geraet.id)

    def _veraltete_geraete_entfernen(self) -> None:
        registry = dr.async_get(self.hass)
        for geraet in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            adressen = [kennung for domain, kennung in geraet.identifiers if domain == DOMAIN]
            if adressen and adressen[0] != self.entry.unique_id and adressen[0] not in self._gekoppelt:
                registry.async_remove_device(geraet.id)

    async def _wiederverbinden(self, _jetzt: datetime | None = None) -> None:
        if not self.entry.options.get(CONF_AUTO_RECONNECT, True):
            return
        if self._lock.locked() or self.bluez.suche_laeuft:
            return
        for adresse, (pfad, geraet) in self.gekoppelte().items():
            einstellung = self._einstellungen.get(adresse, {})
            if geraet.get("Connected") or not einstellung.get("wach", True) or einstellung.get("manuell_getrennt"):
                continue
            async with self._lock:
                try:
                    await self.bluez.verbinden(pfad)
                except BluetoothError as err:
                    _LOGGER.debug("Wiederverbinden mit %s nicht möglich: %s", adresse, err)
