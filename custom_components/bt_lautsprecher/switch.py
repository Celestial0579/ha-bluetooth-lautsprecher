"""Schalter je Lautsprecher: Verbunden und Wach halten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GeraeteEntitaet
from .steuerung import Steuerung


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    steuerung: Steuerung = entry.runtime_data

    @callback
    def neue_geraete(adressen: list[str]) -> None:
        async_add_entities(
            e for a in adressen for e in (VerbundenSchalter(steuerung, a), WachSchalter(steuerung, a))
        )

    neue_geraete(sorted(steuerung.gekoppelte()))
    entry.async_on_unload(async_dispatcher_connect(hass, steuerung.signal_neu, neue_geraete))


class VerbundenSchalter(GeraeteEntitaet, SwitchEntity):
    """Ein: verbinden. Aus: trennen (danach kein automatisches Wiederverbinden)."""

    _attr_icon = "mdi:bluetooth-audio"

    def __init__(self, steuerung: Steuerung, adresse: str) -> None:
        super().__init__(steuerung, adresse, "verbunden")

    @property
    def is_on(self) -> bool:
        return self._st.ist_verbunden(self._adresse)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._st.async_verbinden(self._adresse)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._st.async_trennen(self._adresse)


class WachSchalter(GeraeteEntitaet, SwitchEntity):
    """Ein: Verbindung halten und unhörbaren Strom senden, damit er nicht abschaltet."""

    _attr_icon = "mdi:sleep-off"

    def __init__(self, steuerung: Steuerung, adresse: str) -> None:
        super().__init__(steuerung, adresse, "wach_halten")

    @property
    def is_on(self) -> bool:
        return self._st.wach(self._adresse)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"strom_aktiv": self._st.wach_aktiv(self._adresse)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._st.async_wach_setzen(self._adresse, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._st.async_wach_setzen(self._adresse, False)
