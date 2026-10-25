"""Sensoren: letzte Aktion und verbundene Lautsprecher."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bluez import geraetename
from .entity import AdapterEntitaet
from .steuerung import Steuerung


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    steuerung: Steuerung = entry.runtime_data
    async_add_entities([StatusSensor(steuerung), VerbundenSensor(steuerung)])


class StatusSensor(AdapterEntitaet, SensorEntity):
    _attr_icon = "mdi:message-text-outline"

    def __init__(self, steuerung: Steuerung) -> None:
        super().__init__(steuerung, "status")

    @property
    def native_value(self) -> str:
        return self._st.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"suche_laeuft": self._st.bluez.suche_laeuft}


class VerbundenSensor(AdapterEntitaet, SensorEntity):
    _attr_icon = "mdi:speaker-bluetooth"

    def __init__(self, steuerung: Steuerung) -> None:
        super().__init__(steuerung, "verbunden")

    @property
    def native_value(self) -> int:
        return sum(1 for _p, g in self._st.gekoppelte().values() if g.get("Connected"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        gekoppelt = self._st.gekoppelte()
        return {
            "verbunden": [geraetename(g) for _p, g in gekoppelt.values() if g.get("Connected")],
            "gekoppelt": [geraetename(g) for _p, g in gekoppelt.values()],
            "gefunden": [geraetename(g) for g in self._st.gefundene().values()],
        }
