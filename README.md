# Bluetooth-Lautsprecher für Home Assistant

Bluetooth-Lautsprecher (A2DP) direkt am Home-Assistant-Server koppeln, verbinden, trennen und
**wach halten** – komplett über die Oberfläche, ohne Kommandozeile.

*English summary below.*

## Was es kann

- **Suchen** nach Lautsprechern in Reichweite (30 Sekunden, nur Audiogeräte)
- **Neues Gerät** auswählen und **koppeln und verbinden**
- je gekoppeltem Lautsprecher ein eigenes Gerät mit
  - Schalter **Verbunden** – ein: verbinden, aus: trennen (danach kein automatisches Wiederverbinden)
  - Schalter **Wach halten** – hält die Verbindung und sendet einen unhörbaren Strom, damit der
    Lautsprecher nicht in den Standby geht; wird er aus- und wieder eingeschaltet, verbindet Home
    Assistant ihn innerhalb von zwei Minuten neu
  - Knopf **Vergessen**
- ein verbundener Lautsprecher wird automatisch zur **Tonausgabe** von Home Assistant
- Sensoren **Letzte Aktion** und **Verbundene Lautsprecher**

## Voraussetzungen

| | |
|---|---|
| Installation | **Home Assistant OS** oder **Supervised** (Audio-Plugin). Unter *Container*/*Core* klappt nur das Koppeln, kein Ton und kein Wachhalten. |
| Bluetooth | Adapter mit **Bluetooth Classic (BR/EDR)**. Reine BLE-Adapter und ESPHome-Bluetooth-Proxys können keinen Ton übertragen. |
| Home Assistant | 2026.10 oder neuer |

**Hardware-Hinweise**

- **Home Assistant Green**: hat kein Bluetooth eingebaut – ein USB-Bluetooth-Adapter mit
  Linux-Unterstützung ist nötig.
- **Raspberry Pi 3/4/5**: das eingebaute Bluetooth funktioniert. Es teilt sich Funkchip und Antenne mit
  dem WLAN; bei Stottern den Pi per Kabel anbinden oder einen USB-Adapter nehmen.
- **Virtuelle Maschine** (z. B. Proxmox): den Bluetooth-Adapter per USB an die VM durchreichen und die
  VM neu starten.
- Reichweite: etwa 10 m, durch Wände deutlich weniger.

## Installation

1. HACS › drei Punkte › **Benutzerdefinierte Repositories** › diese Repository-URL, Typ **Integration**.
2. „Bluetooth-Lautsprecher“ installieren und Home Assistant neu starten.
3. **Einstellungen › Geräte & Dienste › Integration hinzufügen › Bluetooth-Lautsprecher**, Adapter wählen.

## Bedienung

1. Lautsprecher in den Kopplungsmodus versetzen.
2. **Suchen** drücken, unter **Neues Gerät** den Lautsprecher wählen, **Koppeln und verbinden** drücken.
3. Ton abspielen über eine App mit Tonausgabe, z. B. die offizielle App **VLC** (wird als Mediaplayer
   eingebunden) oder **Music Assistant**.

Optionen (Integration › Konfigurieren): automatisch wieder verbinden, Lautsprecher als Tonausgabe
festlegen, mit sehr leisem Rauschen statt Stille wach halten (für Lautsprecher, die trotz Stille
abschalten).

## Hinweise

- **Wach halten** sendet Stille per ffmpeg an die Bluetooth-Ausgabe. Akku-Lautsprecher schalten dann nicht
  mehr von selbst ab und entladen sich entsprechend.
- Der Kopplungsagent nimmt nur Kopplungen an, die über die Oberfläche angestoßen wurden, oder von bereits
  vertrauenswürdigen Geräten; fremde Kopplungsversuche werden abgewiesen.
- Bluetooth hat rund 0,2 Sekunden Verzögerung; gemeinsam mit anderen Lautsprechern läuft es nicht ganz synchron.

---

## English summary

Pair, connect, disconnect and keep Bluetooth (A2DP) speakers awake on the Home Assistant host – entirely from
the UI. Requires Home Assistant OS or Supervised (audio plugin) and a Bluetooth Classic (BR/EDR) adapter;
BLE-only adapters and ESPHome proxies cannot carry audio. Home Assistant Green has no built-in Bluetooth
(use a USB adapter). Install via HACS as a custom repository (type *Integration*), restart, then add
“Bluetooth-Lautsprecher” under *Settings › Devices & services*. Play audio through an app with audio
output such as the official VLC app or Music Assistant.

Lizenz / License: MIT
