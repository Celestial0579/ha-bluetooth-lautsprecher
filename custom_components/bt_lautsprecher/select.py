"""Auswahl eines gefundenen, noch nicht gekoppelten Lautsprechers."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bluez import geraetename
from .entity import AdapterEntitaet
from .steuerung import Steuerung


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([NeuesGeraetAuswahl(entry.runtime_data)])


class NeuesGeraetAuswahl(AdapterEntitaet, SelectEntity):
    _attr_icon = "mdi:speaker-wireless"

    def __init__(self, steuerung: Steuerung) -> None:
        super().__init__(steuerung, "neues_geraet")

    def _bezeichnungen(self) -> dict[str, str]:
        return {
            f"{geraetename(g)} ({g.get('Address')})": pfad
            for pfad, g in sorted(self._st.gefundene().items(), key=lambda e: geraetename(e[1]).lower())
        }

    @property
    def options(self) -> list[str]:
        return list(self._bezeichnungen())

    @property
    def current_option(self) -> str | None:
        for bezeichnung, pfad in self._bezeichnungen().items():
            if pfad == self._st.neu_auswahl:
                return bezeichnung
        return None

    async def async_select_option(self, option: str) -> None:
        self._st.neu_auswahl = self._bezeichnungen().get(option)
        self.async_write_ha_state()
