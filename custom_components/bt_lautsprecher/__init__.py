"""Bluetooth-Lautsprecher: Lautsprecher per Oberfläche koppeln, verbinden und wach halten."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .bluez import BluetoothError
from .const import DOMAIN
from .steuerung import Steuerung

PLATFORMS = [Platform.BUTTON, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

type BtLautsprecherConfigEntry = ConfigEntry[Steuerung]


async def async_setup_entry(hass: HomeAssistant, entry: BtLautsprecherConfigEntry) -> bool:
    steuerung = Steuerung(hass, entry)
    try:
        await steuerung.async_start()
    except BluetoothError as err:
        await steuerung.async_stop()
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = steuerung
    await er.async_migrate_entries(hass, entry.entry_id, lambda e: _neue_kennung(entry, e))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_optionen_geaendert))
    return True


def _neue_kennung(entry: BtLautsprecherConfigEntry, eintrag: er.RegistryEntry) -> dict[str, str] | None:
    """Bis 0.1.0 fehlte der Adapter in der Kennung der Lautsprecher-Entitäten (<Lautsprecher>_<Schlüssel>)."""
    adapter = str(entry.unique_id)
    if eintrag.unique_id.startswith(f"{adapter}_"):
        return None  # Entität des Adapters oder schon neu
    return {"new_unique_id": f"{adapter}_{eintrag.unique_id}"}


async def async_unload_entry(hass: HomeAssistant, entry: BtLautsprecherConfigEntry) -> bool:
    if ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: BtLautsprecherConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Löschen in der Oberfläche nur für nicht mehr gekoppelte Lautsprecher."""
    adressen = {kennung for domain, kennung in device.identifiers if domain == DOMAIN}
    if entry.unique_id in adressen:
        return False
    return not adressen & set(entry.runtime_data.gekoppelte())


async def _optionen_geaendert(hass: HomeAssistant, entry: BtLautsprecherConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
