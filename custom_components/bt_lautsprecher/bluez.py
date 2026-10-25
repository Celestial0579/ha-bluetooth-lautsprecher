"""Anbindung an BlueZ über D-Bus (Bluetooth Classic / BR-EDR).

Absichtlich ohne ``from __future__ import annotations``: dbus-fast liest die
D-Bus-Signaturen aus den Annotationen des Agenten.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

from .const import AUDIO_UUIDS

_LOGGER = logging.getLogger(__name__)

BLUEZ = "org.bluez"
IFACE_ADAPTER = "org.bluez.Adapter1"
IFACE_DEVICE = "org.bluez.Device1"
IFACE_AGENT_MANAGER = "org.bluez.AgentManager1"
IFACE_PROPS = "org.freedesktop.DBus.Properties"
IFACE_OM = "org.freedesktop.DBus.ObjectManager"
AGENT_PATH = "/io/github/celestial0579/bt_lautsprecher/agent"


class BluetoothError(Exception):
    """Fehler beim Sprechen mit BlueZ."""


def _auspacken(wert: Any) -> Any:
    return wert.value if isinstance(wert, Variant) else wert


def _eigenschaften(roh: dict[str, Any]) -> dict[str, Any]:
    return {schluessel: _auspacken(wert) for schluessel, wert in roh.items()}


def ist_audio(geraet: dict[str, Any]) -> bool:
    """Ist das Gerät ein Lautsprecher/Kopfhörer?"""
    if str(geraet.get("Icon", "")).startswith("audio"):
        return True
    klasse = geraet.get("Class")
    if isinstance(klasse, int) and (klasse >> 8) & 0x1F == 4:
        return True
    uuids = {str(u).lower() for u in geraet.get("UUIDs", [])}
    return bool(uuids & AUDIO_UUIDS)


def geraetename(geraet: dict[str, Any]) -> str:
    """Anzeigename eines Geräts."""
    return str(geraet.get("Alias") or geraet.get("Name") or geraet.get("Address", "?"))


async def adapter_liste() -> dict[str, dict[str, str]]:
    """Alle Bluetooth-Adapter als {Objektpfad: {"name": ..., "adresse": ...}}."""
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        antwort = await bus.call(
            Message(destination=BLUEZ, path="/", interface=IFACE_OM, member="GetManagedObjects")
        )
        if antwort.message_type == MessageType.ERROR:
            return {}
        ergebnis = {}
        for pfad, schnittstellen in antwort.body[0].items():
            if IFACE_ADAPTER in schnittstellen:
                adresse = str(_auspacken(schnittstellen[IFACE_ADAPTER].get("Address", "")))
                ergebnis[pfad] = {"name": pfad.rsplit("/", 1)[-1], "adresse": adresse}
        return ergebnis
    finally:
        bus.disconnect()


class _Agent(ServiceInterface):
    """Kopplungsagent: nimmt nur angeforderte oder vertrauenswürdige Geräte an."""

    def __init__(self, verwalter: "BluezVerwalter") -> None:
        super().__init__("org.bluez.Agent1")
        self._verwalter = verwalter

    def _pruefen(self, geraet: str) -> None:
        if not self._verwalter.darf_koppeln(geraet):
            _LOGGER.info("Kopplungsanfrage von %s abgewiesen", geraet)
            raise DBusError("org.bluez.Error.Rejected", "Kopplung wurde nicht angefordert")

    @method()
    def Release(self):  # noqa: N802
        return

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
        self._pruefen(device)
        return "0000"

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
        self._pruefen(device)

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821
        self._pruefen(device)
        return 0

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
        return

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
        self._pruefen(device)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802, F821
        self._pruefen(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
        self._pruefen(device)

    @method()
    def Cancel(self):  # noqa: N802
        return


class BluezVerwalter:
    """Hält die Geräteliste eines Adapters aktuell und führt Aktionen aus."""

    def __init__(self, adapter_pfad: str) -> None:
        self.adapter_pfad = adapter_pfad
        self.geraete: dict[str, dict[str, Any]] = {}
        self.suche_laeuft = False
        self._bus: MessageBus | None = None
        self._zuhoerer: list[Callable[[], None]] = []
        self._kopplungsziel: str | None = None
        self._praefix = adapter_pfad + "/dev_"

    # ------------------------------------------------------------ Lebenszyklus
    async def start(self) -> None:
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except Exception as err:  # noqa: BLE001
            raise BluetoothError(f"D-Bus nicht erreichbar: {err}") from err
        self._bus.add_message_handler(self._nachricht)
        for regel in (
            f"type='signal',sender='{BLUEZ}',interface='{IFACE_OM}'",
            f"type='signal',sender='{BLUEZ}',interface='{IFACE_PROPS}',member='PropertiesChanged'",
        ):
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[regel],
                )
            )
        await self._laden()
        await self._agent_anmelden()

    async def stop(self) -> None:
        if self._bus is None:
            return
        try:
            await self._aufruf("/org/bluez", IFACE_AGENT_MANAGER, "UnregisterAgent", "o", [AGENT_PATH])
        except BluetoothError:
            pass
        self._bus.disconnect()
        self._bus = None

    def zuhoerer_hinzufuegen(self, rueckruf: Callable[[], None]) -> Callable[[], None]:
        self._zuhoerer.append(rueckruf)
        return lambda: self._zuhoerer.remove(rueckruf)

    # ------------------------------------------------------------ Aktionen
    async def suchen(self, sekunden: int) -> None:
        if self.suche_laeuft:
            return
        self.suche_laeuft = True
        self._melden()
        try:
            try:
                await self._aufruf(
                    self.adapter_pfad, IFACE_ADAPTER, "SetDiscoveryFilter", "a{sv}",
                    [{"Transport": Variant("s", "bredr")}],
                )
            except BluetoothError as err:
                _LOGGER.debug("Suchfilter nicht gesetzt: %s", err)
            await self._aufruf(self.adapter_pfad, IFACE_ADAPTER, "StartDiscovery")
            await asyncio.sleep(sekunden)
        finally:
            await self._suche_stoppen()
            self.suche_laeuft = False
            self._melden()

    async def verbinden(self, pfad: str) -> None:
        geraet = self.geraete.get(pfad)
        if geraet is None:
            raise BluetoothError("Gerät ist nicht mehr bekannt")
        if self.suche_laeuft:
            await self._suche_stoppen()
        if not geraet.get("Paired"):
            self._kopplungsziel = pfad
            try:
                await self._aufruf(pfad, IFACE_DEVICE, "Pair", zeit=60)
            except BluetoothError as err:
                if "AlreadyExists" not in str(err):
                    raise
            finally:
                self._kopplungsziel = None
        if not geraet.get("Trusted"):
            await self._aufruf(pfad, IFACE_PROPS, "Set", "ssv", [IFACE_DEVICE, "Trusted", Variant("b", True)])
        await self._aufruf(pfad, IFACE_DEVICE, "Connect", zeit=30)

    async def trennen(self, pfad: str) -> None:
        await self._aufruf(pfad, IFACE_DEVICE, "Disconnect", zeit=20)

    async def vergessen(self, pfad: str) -> None:
        await self._aufruf(self.adapter_pfad, IFACE_ADAPTER, "RemoveDevice", "o", [pfad], zeit=20)

    def darf_koppeln(self, pfad: str) -> bool:
        return pfad == self._kopplungsziel or bool(self.geraete.get(pfad, {}).get("Trusted"))

    # ------------------------------------------------------------ intern
    async def _suche_stoppen(self) -> None:
        try:
            await self._aufruf(self.adapter_pfad, IFACE_ADAPTER, "StopDiscovery")
        except BluetoothError as err:
            _LOGGER.debug("Suche nicht gestoppt: %s", err)

    async def _aufruf(
        self, pfad: str, schnittstelle: str, name: str, signatur: str = "",
        inhalt: list[Any] | None = None, zeit: float = 10,
    ) -> list[Any]:
        if self._bus is None:
            raise BluetoothError("Nicht mit D-Bus verbunden")
        nachricht = Message(
            destination=BLUEZ, path=pfad, interface=schnittstelle, member=name,
            signature=signatur, body=inhalt or [],
        )
        try:
            async with asyncio.timeout(zeit):
                antwort = await self._bus.call(nachricht)
        except TimeoutError as err:
            raise BluetoothError(f"{name}: keine Antwort nach {zeit:.0f} s") from err
        if antwort.message_type == MessageType.ERROR:
            text = antwort.body[0] if antwort.body else ""
            raise BluetoothError(f"{antwort.error_name}: {text}")
        return antwort.body

    async def _laden(self) -> None:
        inhalt = await self._aufruf("/", IFACE_OM, "GetManagedObjects")
        self.geraete = {
            pfad: _eigenschaften(schnittstellen[IFACE_DEVICE])
            for pfad, schnittstellen in inhalt[0].items()
            if pfad.startswith(self._praefix) and IFACE_DEVICE in schnittstellen
        }

    async def _agent_anmelden(self) -> None:
        assert self._bus is not None
        self._bus.export(AGENT_PATH, _Agent(self))
        try:
            await self._aufruf("/org/bluez", IFACE_AGENT_MANAGER, "RegisterAgent", "os", [AGENT_PATH, "NoInputNoOutput"])
        except BluetoothError as err:
            if "AlreadyExists" not in str(err):
                _LOGGER.warning("Kopplungsagent nicht angemeldet: %s", err)
                return
        try:
            await self._aufruf("/org/bluez", IFACE_AGENT_MANAGER, "RequestDefaultAgent", "o", [AGENT_PATH])
        except BluetoothError as err:
            _LOGGER.debug("Kein Standard-Agent: %s", err)

    def _nachricht(self, nachricht: Message) -> None:
        if nachricht.message_type != MessageType.SIGNAL:
            return None
        geaendert = False
        if nachricht.member == "InterfacesAdded":
            pfad, schnittstellen = nachricht.body
            if pfad.startswith(self._praefix) and IFACE_DEVICE in schnittstellen:
                self.geraete[pfad] = _eigenschaften(schnittstellen[IFACE_DEVICE])
                geaendert = True
        elif nachricht.member == "InterfacesRemoved":
            pfad, schnittstellen = nachricht.body
            if IFACE_DEVICE in schnittstellen and self.geraete.pop(pfad, None) is not None:
                geaendert = True
        elif nachricht.member == "PropertiesChanged":
            schnittstelle, werte, _ungueltig = nachricht.body
            if schnittstelle == IFACE_DEVICE and nachricht.path in self.geraete:
                self.geraete[nachricht.path].update(_eigenschaften(werte))
                geaendert = True
        if geaendert:
            self._melden()
        return None

    def _melden(self) -> None:
        for rueckruf in list(self._zuhoerer):
            try:
                rueckruf()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Fehler im Zuhörer")
