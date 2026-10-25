"""Knöpfe: Suchen und Koppeln (Adapter), Vergessen (je Lautsprecher)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AdapterEntitaet, GeraeteEntitaet
from .steuerung import Steuerung


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    steuerung: Steuerung = entry.runtime_data
    async_add_entities([SuchenKnopf(steuerung), KoppelnKnopf(steuerung)])

    @callback
    def neue_geraete(adressen: list[str]) -> None:
        async_add_entities(VergessenKnopf(steuerung, a) for a in adressen)

    neue_geraete(sorted(steuerung.gekoppelte()))
    entry.async_on_unload(async_dispatcher_connect(hass, steuerung.signal_neu, neue_geraete))


class SuchenKnopf(AdapterEntitaet, ButtonEntity):
    _attr_icon = "mdi:bluetooth-settings"

    def __init__(self, steuerung: Steuerung) -> None:
        super().__init__(steuerung, "suchen")

    async def async_press(self) -> None:
        await self._st.async_suchen()


class KoppelnKnopf(AdapterEntitaet, ButtonEntity):
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, steuerung: Steuerung) -> None:
        super().__init__(steuerung, "koppeln")

    async def async_press(self) -> None:
        await self._st.async_koppeln()


class VergessenKnopf(GeraeteEntitaet, ButtonEntity):
    _attr_icon = "mdi:bluetooth-off"

    def __init__(self, steuerung: Steuerung, adresse: str) -> None:
        super().__init__(steuerung, adresse, "vergessen")

    async def async_press(self) -> None:
        await self._st.async_vergessen(self._adresse)
