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


def _signal(member: str, body: list, path: str = "/") -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.SIGNAL, member=member, body=body, path=path)


def test_geraeteliste_aus_signalen() -> None:
    verwalter = BluezVerwalter(ADAPTER)
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
