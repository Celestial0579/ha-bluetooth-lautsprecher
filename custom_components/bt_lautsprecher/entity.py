"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .steuerung import Steuerung


class _Basis(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, steuerung: Steuerung, schluessel: str) -> None:
        self._st = steuerung
        self._attr_translation_key = schluessel

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self._st.signal, self._aktualisieren))

    @callback
    def _aktualisieren(self) -> None:
        self.async_write_ha_state()


class AdapterEntitaet(_Basis):
    """Gehört zum Bluetooth-Adapter."""

    def __init__(self, steuerung: Steuerung, schluessel: str) -> None:
        super().__init__(steuerung, schluessel)
        kennung = str(steuerung.entry.unique_id)
        self._attr_unique_id = f"{kennung}_{schluessel}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, kennung)},
            connections={(dr.CONNECTION_BLUETOOTH, kennung)},
            name="Bluetooth-Lautsprecher",
            manufacturer="BlueZ",
            model=f"Adapter {steuerung.bluez.adapter_pfad.rsplit('/', 1)[-1]}",
        )


class GeraeteEntitaet(_Basis):
    """Gehört zu einem gekoppelten Lautsprecher."""

    def __init__(self, steuerung: Steuerung, adresse: str, schluessel: str) -> None:
        super().__init__(steuerung, schluessel)
        self._adresse = adresse
        self._attr_unique_id = f"{adresse}_{schluessel}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, adresse)},
            connections={(dr.CONNECTION_BLUETOOTH, adresse)},
            name=steuerung.name(adresse),
            via_device_id=steuerung.adapter_geraet_id,
        )

    @property
    def available(self) -> bool:
        return self._adresse in self._st.gekoppelte()
