"""Konstanten für Bluetooth-Lautsprecher."""

DOMAIN = "bt_lautsprecher"

CONF_ADAPTER = "adapter"
CONF_AUTO_RECONNECT = "auto_reconnect"
CONF_DEFAULT_OUTPUT = "default_output"
CONF_KEEPALIVE_NOISE = "keepalive_noise"

SIGNAL_UPDATE = "bt_lautsprecher_update_{}"
SIGNAL_NEW_DEVICES = "bt_lautsprecher_new_{}"

DISCOVERY_SECONDS = 30
RECONNECT_INTERVAL_SECONDS = 120

# A2DP Audio Sink / Advanced Audio Distribution
AUDIO_UUIDS = {
    "0000110b-0000-1000-8000-00805f9b34fb",
    "0000110d-0000-1000-8000-00805f9b34fb",
}
