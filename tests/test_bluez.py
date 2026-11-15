"""Tests für die BlueZ-Anbindung ohne D-Bus."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dbus_fast import DBusError, MessageType, Variant
import pytest

from custom_components.bt_lautsprecher import bluez
from custom_components.bt_lautsprecher.bluez import (
    IFACE_DEVICE,
    BluezVerwalter,
    _Agent,
    geraetename,
    ist_audio,
)
from custom_components.bt_lautsprecher.wachhalten import senke

ADAPTER = "/org/bluez/hci0"
BOX = f"{ADAPTER}/dev_AA_BB_CC_DD_EE_FF"
FREMD = f"{ADAPTER}/dev_11_22_33_44_55_66"


@pytest.mark.parametrize(
    ("geraet", "erwartet"),
    [
        ({"Icon": "audio-card"}, True),
        ({"Class": 0x240404}, True),  # Hauptklasse 4: Audio/Video
        ({"UUIDs": ["0000110B-0000-1000-8000-00805F9B34FB"]}, True),
        ({"Icon": "input-keyboard", "Class": 0x2540}, False),
        ({"Class": "kein int"}, False),
        ({}, False),
    ],
)
def test_ist_audio(geraet: dict, erwartet: bool) -> None:
    assert ist_audio(geraet) is erwartet


def test_geraetename() -> None:
    assert geraetename({"Alias": "Box", "Name": "JBL", "Address": "A"}) == "Box"
    assert geraetename({"Name": "JBL", "Address": "A"}) == "JBL"
    assert geraetename({"Address": "A"}) == "A"
    assert geraetename({}) == "?"


def test_agent_nimmt_nur_das_angeforderte_geraet() -> None:
    """Auch eine schon vertrauenswürdige Adresse darf keine neue Kopplung beginnen."""
    verwalter = BluezVerwalter(ADAPTER)
    verwalter.geraete = {BOX: {"Trusted": True, "Paired": True}, FREMD: {}}
    agent = _Agent(verwalter)

    assert not verwalter.darf_koppeln(BOX)
    with pytest.raises(DBusError):
        agent._pruefen(BOX)

    verwalter._kopplungsziel = BOX
    assert verwalter.darf_koppeln(BOX)
    agent._pruefen(BOX)
    assert not verwalter.darf_koppeln(FREMD)
    with pytest.raises(DBusError):
        agent._pruefen(FREMD)


SIGNATUR = {"InterfacesAdded": ("oa{sa{sv}}", bluez.IFACE_OM), "InterfacesRemoved": ("oas", bluez.IFACE_OM),
            "PropertiesChanged": ("sa{sv}as", bluez.IFACE_PROPS)}


def _signal(member: str, body: list, path: str = "/", sender: str = ":1.5", signatur: str | None = None) -> SimpleNamespace:
    sig, iface = SIGNATUR[member]
    return SimpleNamespace(message_type=MessageType.SIGNAL, member=member, body=body, path=path,
                           sender=sender, interface=iface, signature=signatur or sig)


def test_signale_nur_vom_eigentuemer_von_bluez() -> None:
    verwalter = BluezVerwalter(ADAPTER)
    verwalter.bluez_name = ":1.5"
    hinzu = [BOX, {IFACE_DEVICE: {"Address": Variant("s", "AA")}}]
    verwalter._nachricht(_signal("InterfacesAdded", hinzu, sender=":1.99"))  # fremder Teilnehmer
    verwalter._nachricht(_signal("InterfacesAdded", hinzu, signatur="s"))  # falsche Signatur
    assert verwalter.geraete == {}
    # BlueZ startet neu und bekommt einen neuen Namen.
    verwalter._nachricht(SimpleNamespace(message_type=MessageType.SIGNAL, sender=bluez.DBUS, interface=bluez.DBUS,
                                         member="NameOwnerChanged", signature="sss", body=["org.bluez", ":1.5", ":1.7"], path="/"))
    assert verwalter.bluez_name == ":1.7"
    verwalter._nachricht(_signal("InterfacesAdded", hinzu, sender=":1.5"))
    assert verwalter.geraete == {}
    verwalter._nachricht(_signal("InterfacesAdded", hinzu, sender=":1.7"))
    assert BOX in verwalter.geraete
    # Ein fremder Teilnehmer kann NameOwnerChanged nicht vortäuschen.
    verwalter._nachricht(SimpleNamespace(message_type=MessageType.SIGNAL, sender=":1.99", interface=bluez.DBUS,
                                         member="NameOwnerChanged", signature="sss", body=["org.bluez", "", ":1.99"], path="/"))
    assert verwalter.bluez_name == ":1.7"


def _eigentuemer(alt: str, neu: str) -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.SIGNAL, sender=bluez.DBUS, interface=bluez.DBUS,
                           member="NameOwnerChanged", signature="sss", body=["org.bluez", alt, neu], path="/")


async def test_neustart_von_bluez_meldet_agent_und_liste_neu() -> None:
    """#8: Nach einem Neustart kennt bluetoothd den Agenten nicht mehr."""
    verwalter = BluezVerwalter(ADAPTER)
    verwalter.bluez_name = ":1.5"
    verwalter.geraete = {BOX: {"Address": "AA"}}
    exportiert: list[str] = []
    verwalter._bus = SimpleNamespace(export=lambda pfad, _obj: exportiert.append(pfad))
    verwalter._agent_exportiert = True  # beim Start schon exportiert
    aufrufe: list[tuple[str, str]] = []

    async def aufruf(pfad, schnittstelle, mitglied, *_args, **_kw):
        aufrufe.append((schnittstelle, mitglied))
        if mitglied == "GetManagedObjects":
            return [{BOX: {IFACE_DEVICE: {"Address": Variant("s", "AA")}}, FREMD: {IFACE_DEVICE: {}}}]
        return []

    verwalter._aufruf = aufruf
    meldungen: list[int] = []
    verwalter.zuhoerer_hinzufuegen(lambda: meldungen.append(1))

    verwalter._nachricht(_eigentuemer(":1.5", ""))  # bluetoothd beendet
    assert verwalter.bluez_name is None and verwalter.geraete == {}
    assert verwalter._neuanmeldung is None
    verwalter._nachricht(_eigentuemer("", ":1.9"))  # wieder da
    assert verwalter._neuanmeldung is not None
    await verwalter._neuanmeldung
    assert verwalter.bluez_name == ":1.9"
    assert set(verwalter.geraete) == {BOX, FREMD}
    assert (bluez.IFACE_AGENT_MANAGER, "RegisterAgent") in aufrufe
    assert (bluez.IFACE_AGENT_MANAGER, "RequestDefaultAgent") in aufrufe
    assert exportiert == []  # nicht doppelt exportiert
    assert len(meldungen) == 2  # Liste geleert, Liste neu


async def test_gleicher_eigentuemer_aendert_nichts() -> None:
    verwalter = BluezVerwalter(ADAPTER)
    verwalter.bluez_name = ":1.5"
    verwalter.geraete = {BOX: {}}
    verwalter._bus = SimpleNamespace()
    verwalter._nachricht(_eigentuemer("", ":1.5"))
    assert verwalter.geraete == {BOX: {}} and verwalter._neuanmeldung is None


def test_geraeteliste_aus_signalen() -> None:
    verwalter = BluezVerwalter(ADAPTER)
    verwalter.bluez_name = ":1.5"
    meldungen: list[int] = []
    verwalter.zuhoerer_hinzufuegen(lambda: meldungen.append(1))

    verwalter._nachricht(
        _signal("InterfacesAdded", [BOX, {IFACE_DEVICE: {"Address": Variant("s", "AA:BB:CC:DD:EE:FF")}}])
    )
    assert verwalter.geraete[BOX] == {"Address": "AA:BB:CC:DD:EE:FF"}
    # Geräte anderer Adapter gehören nicht dazu.
    verwalter._nachricht(_signal("InterfacesAdded", ["/org/bluez/hci1/dev_X", {IFACE_DEVICE: {}}]))
    assert "/org/bluez/hci1/dev_X" not in verwalter.geraete

    verwalter._nachricht(
        _signal("PropertiesChanged", [IFACE_DEVICE, {"Connected": Variant("b", True)}, []], path=BOX)
    )
    assert verwalter.geraete[BOX]["Connected"] is True

    verwalter._nachricht(_signal("InterfacesRemoved", [BOX, [IFACE_DEVICE]]))
    assert BOX not in verwalter.geraete
    assert len(meldungen) == 3


async def test_adapter_liste_hat_eine_zeitgrenze(monkeypatch: pytest.MonkeyPatch) -> None:
    class HaengenderBus:
        def __init__(self, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            await asyncio.sleep(60)

    monkeypatch.setattr(bluez, "MessageBus", HaengenderBus)
    monkeypatch.setattr(bluez, "ADAPTER_ZEIT", 0.05)
    with pytest.raises(TimeoutError):
        await bluez.adapter_liste()


def test_senke() -> None:
    assert senke("aa:bb:cc:dd:ee:ff") == "bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink"
