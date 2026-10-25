"""Tonausgabe über die Supervisor-API (nur Home Assistant OS / Supervised)."""

from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)


def supervisor_vorhanden() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


async def standard_ausgabe_setzen(sitzung: ClientSession, adresse: str, versuche: int = 20) -> bool:
    """Bluetooth-Ausgabe des Geräts als Standard-Tonausgabe setzen."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False
    basis = f"http://{os.environ.get('SUPERVISOR', 'supervisor')}"
    kopf = {"Authorization": f"Bearer {token}"}
    marke = adresse.replace(":", "_").upper()
    for _ in range(versuche):
        try:
            async with sitzung.get(f"{basis}/audio/info", headers=kopf) as antwort:
                daten = await antwort.json()
            ausgaenge = (daten.get("data") or {}).get("audio", {}).get("output", [])
            treffer = next((a for a in ausgaenge if marke in str(a.get("name", "")).upper()), None)
            if treffer:
                if treffer.get("default"):
                    return True
                async with sitzung.post(
                    f"{basis}/audio/default/output", headers=kopf, json={"name": treffer["name"]}
                ) as antwort:
                    return antwort.status == 200
        except (ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Supervisor-Audio nicht erreichbar: %s", err)
        await asyncio.sleep(1)
    return False
