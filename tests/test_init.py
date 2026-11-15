"""Tests der Einrichtung mit nachgebautem BlueZ."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

from aiohttp import ClientTimeout, web
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.bt_lautsprecher import supervisor
from custom_components.bt_lautsprecher.const import DOMAIN

BOX = "AA:BB:CC:DD:EE:FF"


class NachbauBluez:
    """Steht für BluezVerwalter; jede Instanz sieht denselben gekoppelten Lautsprecher."""

    def __init__(self, adapter_pfad: str) -> None:
        self.adapter_pfad = adapter_pfad
        self.suche_laeuft = False
        self._zuhoerer: list[Callable[[], None]] = []
        self.geraete: dict[str, dict[str, Any]] = {
            f"{adapter_pfad}/dev_AA_BB_CC_DD_EE_FF": {
                "Address": BOX, "Alias": "Box", "Icon": "audio-card",
                "Paired": True, "Trusted": True, "Connected": False,
            }
        }

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    def zuhoerer_hinzufuegen(self, rueckruf: Callable[[], None]) -> Callable[[], None]:
        self._zuhoerer.append(rueckruf)
        return lambda: self._zuhoerer.remove(rueckruf)

    async def vergessen(self, pfad: str) -> None:
        self.geraete.pop(pfad)
        for rueckruf in list(self._zuhoerer):
            rueckruf()


@pytest.fixture(autouse=True)
def nachbau() -> Generator[None]:
    with patch("custom_components.bt_lautsprecher.steuerung.BluezVerwalter", NachbauBluez):
        yield


def _eintrag(hass: HomeAssistant, adapter: str, adresse: str) -> MockConfigEntry:
    eintrag = MockConfigEntry(domain=DOMAIN, unique_id=adresse, data={"adapter": f"/org/bluez/{adapter}"})
    eintrag.add_to_hass(hass)
    return eintrag


async def test_kennungen_mit_adapter_und_umstellung(hass: HomeAssistant) -> None:
    eintrag = _eintrag(hass, "hci0", "00:00:00:00:00:01")
    register = er.async_get(hass)
    alt = register.async_get_or_create(
        "switch", DOMAIN, f"{BOX}_verbunden", config_entry=eintrag, suggested_object_id="box_verbunden"
    )

    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await hass.async_block_till_done()
    assert eintrag.state is ConfigEntryState.LOADED

    umgestellt = register.async_get(alt.entity_id)
    assert umgestellt.unique_id == f"00:00:00:00:00:01_{BOX}_verbunden"
    kennungen = {e.unique_id for e in er.async_entries_for_config_entry(register, eintrag.entry_id)}
    assert f"00:00:00:00:00:01_{BOX}_wach_halten" in kennungen
    assert "00:00:00:00:00:01_status" in kennungen  # Adapter-Entität bleibt, wie sie war


async def test_ein_lautsprecher_an_zwei_adaptern(hass: HomeAssistant) -> None:
    erster = _eintrag(hass, "hci0", "00:00:00:00:00:01")
    zweiter = _eintrag(hass, "hci1", "00:00:00:00:00:02")
    assert await hass.config_entries.async_setup(erster.entry_id)  # richtet beide ein
    await hass.async_block_till_done()
    assert zweiter.state is ConfigEntryState.LOADED

    register = er.async_get(hass)
    for eintrag in (erster, zweiter):
        schalter = [
            e for e in er.async_entries_for_config_entry(register, eintrag.entry_id) if e.domain == "switch"
        ]
        assert len(schalter) == 2

    # Vergessen am ersten Adapter entfernt nur dessen Gerät.
    geraete = dr.async_get(hass)
    await erster.runtime_data.async_vergessen(BOX)
    await hass.async_block_till_done()
    assert geraete.async_get_device_by_identifier((DOMAIN, BOX), erster.entry_id) is None
    assert geraete.async_get_device_by_identifier((DOMAIN, BOX), zweiter.entry_id) is not None


async def test_einrichtungsdialog(hass: HomeAssistant) -> None:
    adapter = {"/org/bluez/hci0": {"name": "hci0", "adresse": "00:00:00:00:00:01"}}
    with patch("custom_components.bt_lautsprecher.config_flow.adapter_liste", return_value=adapter):
        ergebnis = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert ergebnis["type"] is FlowResultType.FORM
        with patch("custom_components.bt_lautsprecher.async_setup_entry", return_value=True):
            ergebnis = await hass.config_entries.flow.async_configure(
                ergebnis["flow_id"], {"adapter": "/org/bluez/hci0"}
            )
    assert ergebnis["type"] is FlowResultType.CREATE_ENTRY
    assert ergebnis["result"].unique_id == "00:00:00:00:00:01"


async def test_einrichtungsdialog_ohne_antwort_von_bluez(hass: HomeAssistant) -> None:
    with patch("custom_components.bt_lautsprecher.config_flow.adapter_liste", side_effect=TimeoutError):
        ergebnis = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert ergebnis["type"] is FlowResultType.ABORT
    assert ergebnis["reason"] == "no_adapter"


@pytest.mark.usefixtures("socket_enabled")
async def test_supervisor_hat_eine_zeitgrenze(
    hass: HomeAssistant, aiohttp_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def haengt(_request: web.Request) -> web.Response:
        await asyncio.sleep(30)
        return web.json_response({})

    app = web.Application()
    app.router.add_get("/audio/info", haengt)
    server = await aiohttp_server(app)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test")
    monkeypatch.setenv("SUPERVISOR", f"127.0.0.1:{server.port}")
    monkeypatch.setattr(supervisor, "ZEIT", ClientTimeout(total=0.1))

    assert await supervisor.standard_ausgabe_setzen(async_get_clientsession(hass), BOX, versuche=1) is False
