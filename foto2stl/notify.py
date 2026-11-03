"""Powiadomienia MQTT (np. do bazy na Raspberry Pi / Home Assistant)."""
from __future__ import annotations

import json
import os
import socket

from .core import log


def mqtt_notify(payload: dict, host=None, topic=None, port=1883, user=None, password=None):
    host = host or os.environ.get("FOTO2STL_MQTT")
    if not host:
        return
    topic = topic or os.environ.get("FOTO2STL_MQTT_TOPIC", "foto2stl/done")
    try:
        import paho.mqtt.publish as publish
        auth = {"username": user, "password": password} if user else None
        payload = dict(payload, host=socket.gethostname())
        publish.single(topic, json.dumps(payload, ensure_ascii=False), hostname=host, port=int(port), auth=auth)
        log(f"MQTT → {host}:{port} {topic}")
    except Exception as e:  # noqa: BLE001
        log(f"MQTT nie powiodło się: {e}")
