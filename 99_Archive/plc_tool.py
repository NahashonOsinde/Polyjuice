# plc_tool.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import os
import time

# Snap7 is required here; keep its import local to this module.
import snap7
from snap7.util import set_real, set_int

# --- Enums & Payload (kept isomorphic with your agent_poc) --------------------

class ChipID(str, Enum):
    HERRINGBONE = "HERRINGBONE"
    BAFFLE = "BAFFLE"

class Manifold(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"

class Mode(str, Enum):
    RUN = "RUN"
    CLEAN = "CLEAN"
    PRESSURE_TEST = "PRESSURE_TEST"

@dataclass
class InputPayload:
    tfr: float
    frr: int
    target_volume: float
    temperature: float
    chip_id: ChipID
    manifold: Manifold
    mode: Mode

# --- Whitelist mapping (parity with agent_poc DB9 layout) ---------------------
# DB9 inputs and a single read-only validation bit you already use.
DB_INPUTS = {
    "TFR":        {"db": 9, "start": 198, "type": "REAL"},  # 198.0
    "FRR":        {"db": 9, "start": 202, "type": "INT"},   # 202.0
    "TARGET_VOL": {"db": 9, "start": 204, "type": "REAL"},  # 204.0
    "TEMP":       {"db": 9, "start": 208, "type": "REAL"},  # 208.0
    "CHIP_ID":    {"db": 9, "start": 212, "type": "INT"},   # 212.0 (0=H,1=B)
    "MANIFOLD":   {"db": 9, "start": 214, "type": "INT"},   # 214.0 (1=S,2=L)
    "MODE":       {"db": 9, "start": 216, "type": "INT"},   # 216.0 (1/2/3)
}
DB_VALID = {"db": 9, "start": 218}  # CRUNCH_VALID bit (byte) for acceptance
# (These mirror your agent_poc.py constants.)  # :contentReference[oaicite:13]{index=13} :contentReference[oaicite:14]{index=14}

# --- Static validation (same logic as your agent_poc) -------------------------

def static_validate(payload: InputPayload) -> tuple[bool, list[str]]:
    msgs, ok = [], True
    if not (0.8 <= payload.tfr <= 15.0):  # mL/min
        msgs.append("TFR must be between 0.8 and 15.0 mL/min"); ok = False
    if payload.frr <= 0:
        msgs.append("FRR must be a positive integer"); ok = False
    if not (5.0 <= payload.temperature <= 60.0):
        msgs.append("Temperature must be between 5°C and 60°C"); ok = False
    if payload.target_volume <= 0:
        msgs.append("Target volume must be positive"); ok = False
    return ok, msgs  # :contentReference[oaicite:15]{index=15}

# --- PLC Writer: safe, whitelisted, tiny surface --------------------------------

class PLCWriter:
    """
    Minimal, safe writer that only exposes whitelisted variables.
    Keeps PLC program/IP private—no arbitrary DB browsing.
    """

    def __init__(
        self,
        ip: Optional[str] = None,
        rack: Optional[int] = None,
        slot: Optional[int] = None,
        connect_on_init: bool = True
    ) -> None:
        self.ip   = ip   or os.getenv("PLC_IP")
        self.rack = rack or int(os.getenv("PLC_RACK", "0"))
        self.slot = slot or int(os.getenv("PLC_SLOT", "1"))
        self.client = snap7.client.Client()
        if connect_on_init:
            self.connect()

    def connect(self) -> None:
        self.client.connect(self.ip, self.rack, self.slot)
        if not self.client.get_connected():
            raise ConnectionError("Failed to connect to PLC")

    def disconnect(self) -> None:
        if self.client.get_connected():
            self.client.disconnect()

    # ---- writes (REAL/INT only) ----
    def _write_real(self, db: int, start: int, value: float) -> None:
        buf = bytearray(4)
        set_real(buf, 0, float(value))
        self.client.db_write(db, start, buf)

    def _write_int(self, db: int, start: int, value: int) -> None:
        buf = bytearray(2)
        set_int(buf, 0, int(value))
        self.client.db_write(db, start, buf)

    def write_payload(self, payload: InputPayload) -> None:
        # TFR
        self._write_real(DB_INPUTS["TFR"]["db"], DB_INPUTS["TFR"]["start"], payload.tfr)
        # FRR (integer ratio)
        self._write_int(DB_INPUTS["FRR"]["db"], DB_INPUTS["FRR"]["start"], payload.frr)
        # Target Volume
        self._write_real(DB_INPUTS["TARGET_VOL"]["db"], DB_INPUTS["TARGET_VOL"]["start"], payload.target_volume)
        # Temperature
        self._write_real(DB_INPUTS["TEMP"]["db"], DB_INPUTS["TEMP"]["start"], payload.temperature)
        # Chip ID mapping: 0=Herringbone, 1=Baffle
        chip_val = 0 if payload.chip_id == ChipID.HERRINGBONE else 1
        self._write_int(DB_INPUTS["CHIP_ID"]["db"], DB_INPUTS["CHIP_ID"]["start"], chip_val)
        # Manifold mapping: 1=Small, 2=Large
        mani_val = 1 if payload.manifold == Manifold.SMALL else 2
        self._write_int(DB_INPUTS["MANIFOLD"]["db"], DB_INPUTS["MANIFOLD"]["start"], mani_val)
        # Mode mapping: 1/2/3
        mode_map = {Mode.RUN: 1, Mode.CLEAN: 2, Mode.PRESSURE_TEST: 3}
        self._write_int(DB_INPUTS["MODE"]["db"], DB_INPUTS["MODE"]["start"], mode_map[payload.mode])
        # (Parity with agent_poc write semantics.)  # :contentReference[oaicite:16]{index=16}

    # ---- validation bit ----
    def read_validation(self) -> bool:
        r = self.client.db_read(DB_VALID["db"], DB_VALID["start"], 1)
        return bool(r[0])  # single byte  # :contentReference[oaicite:17]{index=17}

    def poll_validation(self, timeout_s: float = 3.0, interval_s: float = 0.1) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.read_validation():
                return True
            time.sleep(interval_s)
        return False
