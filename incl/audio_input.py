"""Устройства записи и воспроизведения, смена устройства по умолчанию."""

from __future__ import annotations

from dataclasses import dataclass

import comtypes
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioUtilities

_com_ready = False


def ensure_com() -> None:
    global _com_ready
    if _com_ready:
        return
    comtypes.CoInitialize()
    _com_ready = True


@dataclass(frozen=True)
class InputDevice:
    id: str
    title: str
    subtitle: str

    @property
    def full_name(self) -> str:
        if self.subtitle:
            return f"{self.title} ({self.subtitle})"
        return self.title


def split_name(name: str) -> tuple[str, str]:
    text = name.strip()
    if text.endswith(")") and " (" in text:
        title, rest = text.rsplit(" (", 1)
        subtitle = rest[:-1].strip()
        if title.strip() and subtitle:
            return title.strip(), subtitle
    return text, ""


def _active_devices(data_flow: int) -> list[InputDevice]:
    ensure_com()
    found = AudioUtilities.GetAllDevices(data_flow, DEVICE_STATE.ACTIVE.value)
    devices: list[InputDevice] = []
    for dev in found:
        name = (dev.FriendlyName or "").strip()
        if not name or not dev.id:
            continue
        title, subtitle = split_name(name)
        devices.append(InputDevice(str(dev.id), title, subtitle))
    return devices


def list_input_devices() -> list[InputDevice]:
    return _active_devices(EDataFlow.eCapture.value)


def list_output_devices() -> list[InputDevice]:
    return _active_devices(EDataFlow.eRender.value)


def current_input_id() -> str | None:
    ensure_com()
    try:
        mic = AudioUtilities.GetMicrophone()
    except Exception:
        return None
    if mic is None:
        return None
    return mic.GetId()


def current_output_id() -> str | None:
    ensure_com()
    try:
        speakers = AudioUtilities.GetSpeakers()
    except Exception:
        return None
    if speakers is None:
        return None
    return speakers.id


def set_default_device(device_id: str) -> None:
    ensure_com()
    AudioUtilities.SetDefaultDevice(
        device_id,
        [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications],
    )


def set_default_input(device_id: str) -> None:
    set_default_device(device_id)


def set_default_output(device_id: str) -> None:
    set_default_device(device_id)