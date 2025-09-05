#!/usr/bin/env python3
"""
plc_tool.py — TAMARA PLC tool interface (standalone)

This module provides a *locked-down* interface to a Siemens S7‑1200 PLC used by TAMARA.
It only exposes whitelisted read/write operations for experiment inputs and a single
validation bit. It **does not** expose any APIs to upload/download PLC programs, nor
to browse arbitrary DB memory. This keeps the core PLC IP on-device.

Whitelisted mapping (DB9 = DB_Experiments_):
- TFR (REAL)          → DB9.DBD198
- FRR (INT)           → DB9.DBW202
- TARGET_VOL (REAL)   → DB9.DBD204
- TEMP (REAL)         → DB9.DBD208
- CHIP_ID (INT)       → DB9.DBW212   (0=HERRINGBONE, 1=BAFFLE)
- MANIFOLD (INT)      → DB9.DBW214   (1=SMALL, 2=LARGE)
- MODE (INT)          → DB9.DBW216   (1=RUN, 2=CLEAN, 3=PRESSURE_TEST)
Read-only:
- CRUNCH_VALID (BOOL) → DB9.DBB218   (byte read, non-zero means TRUE)

These addresses and the typed fields mirror `agent_poc_V0.py`.

Safeguards
----------
- Only the above DB fields can be read/written via this module.
- If python-snap7 isn’t available or a PLC isn’t reachable, a safe in-memory simulator
  is used so the code still runs for development and tests.

"""

from __future__ import annotations
import os
import time
import logging
import logging.handlers
from dotenv import load_dotenv
from dataclasses import dataclass
from enum import Enum

# --- optional dependency (snap7) ------------------------------------------------
try:
    import snap7  # type: ignore
    from snap7.util import set_real, set_int  # no read helpers needed for our usage
except Exception:  # ImportError or runtime errors
    snap7 = None

# Load environment variables
load_dotenv()

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
# logger = logging.getLogger("tamara.plc")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/tamara_plc.log',
            maxBytes=1024*1024,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Types and whitelisted mapping
# ----------------------------------------------------------------------------

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

# PLC DB Constants for inputs (from agent_poc.py)
DB_CONFIG = {
    'INPUTS': {
        'TFR':         {'db_number': 9, 'start': 198, 'type': 'REAL'},
        'FRR':         {'db_number': 9, 'start': 202, 'type': 'INT'},
        'TARGET_VOL':  {'db_number': 9, 'start': 204, 'type': 'REAL'},
        'TEMP':        {'db_number': 9, 'start': 208, 'type': 'REAL'},
        'CHIP_ID':     {'db_number': 9, 'start': 212, 'type': 'INT'},
        'MANIFOLD':    {'db_number': 9, 'start': 214, 'type': 'INT'},
        'STATUS':      {'db_number': 9, 'start': 216, 'type': 'INT'},
        'COMMAND_START': {'db_number': 9, 'start': 218.0, 'type': 'BOOL'},
        'COMMAND_PAUSE_PLAY': {'db_number': 9, 'start': 218.1, 'type': 'BOOL'},
        'COMMAND_STOP': {'db_number': 9, 'start': 218.2, 'type': 'BOOL'},
    },
    'VALIDATION': {
        # In the POC this is treated as a byte read where non-zero means TRUE.
        'CRUNCH_VALID': {'db_number': 9, 'start': 218.3, 'type': 'BOOL'}
    }
}

# ----------------------------------------------------------------------------
# Safe simulator (used when snap7 is not available or PLC is unreachable)
# ----------------------------------------------------------------------------

class _SimClient:
    """Minimal in-memory simulator mirroring the subset of snap7 API we use."""
    def __init__(self) -> None:
        self._connected = False
        # simulate DB9 bytes (we touch 198..218 plus control bits)
        self._db = bytearray(219)  # size enough to include address 218
        self._debug = bool(int(os.getenv('PLC_SIM_DEBUG', '0')))

    def connect(self, *_args, **_kwargs) -> None:
        self._connected = True
        if self._debug:
            logger.info("SIM: Connected")

    def disconnect(self) -> None:
        self._connected = False
        if self._debug:
            logger.info("SIM: Disconnected")

    def get_connected(self) -> bool:
        return self._connected

    def db_write(self, db_number: int, start: int, data: bytes) -> None:
        if db_number != 9:
            raise PermissionError("Write blocked by whitelist. Only DB9 is allowed.")
        end = start + len(data)
        if end > len(self._db):
            self._db.extend(b'\\x00' * (end - len(self._db)))
        self._db[start:end] = data
        if self._debug:
            logger.info(f"SIM: Write DB{db_number}.DBB{start} = {[hex(b) for b in data]}")

    def db_read(self, db_number: int, start: int, size: int) -> bytes:
        if db_number != 9:
            raise PermissionError("Read blocked by whitelist. Only DB9 is allowed.")
        end = start + size
        if end > len(self._db):
            self._db.extend(b'\\x00' * (end - len(self._db)))
        result = bytes(self._db[start:end])
        if self._debug:
            logger.info(f"SIM: Read DB{db_number}.DBB{start} = {[hex(b) for b in result]}")
        return result

    def db_write_bit(self, db_number: int, byte_offset: int, bit_offset: int, value: int) -> None:
        """Write a single bit in the DB."""
        if db_number != 9:
            raise PermissionError("Write blocked by whitelist. Only DB9 is allowed.")
        if byte_offset >= len(self._db):
            self._db.extend(b'\\x00' * (byte_offset - len(self._db) + 1))
        
        # Get current byte
        current_byte = self._db[byte_offset]
        
        # Modify bit
        if value:
            new_byte = current_byte | (1 << bit_offset)
        else:
            new_byte = current_byte & ~(1 << bit_offset)
            
        # Write back
        self._db[byte_offset] = new_byte
        if self._debug:
            logger.info(f"SIM: Write DB{db_number}.DBX{byte_offset}.{bit_offset} = {value}")

    def db_read_bit(self, db_number: int, byte_offset: int, bit_offset: int) -> bool:
        """Read a single bit from the DB."""
        if db_number != 9:
            raise PermissionError("Read blocked by whitelist. Only DB9 is allowed.")
        if byte_offset >= len(self._db):
            self._db.extend(b'\\x00' * (byte_offset - len(self._db) + 1))
            
        # Get byte and check bit
        current_byte = self._db[byte_offset]
        result = bool(current_byte & (1 << bit_offset))
        if self._debug:
            logger.info(f"SIM: Read DB{db_number}.DBX{byte_offset}.{bit_offset} = {result}")
        return result

# ----------------------------------------------------------------------------
# PLC interface
# ----------------------------------------------------------------------------

class PLCInterface:
    """Locked-down PLC interface for TAMARA."""
    def __init__(self, ip: str | None = None, rack: int = 0, slot: int = 1, simulate: bool | None = None) -> None:
        # Use provided values or environment variables with defaults
        self.ip = ip or os.getenv('PLC_IP', '192.168.0.1')
        self.rack = rack if ip is not None else int(os.getenv('PLC_RACK', '0'))
        self.slot = slot if ip is not None else int(os.getenv('PLC_SLOT', '1'))
        # Pick transport
        use_sim = simulate if simulate is not None else bool(int(os.getenv('PLC_SIM', '1')))
        if snap7 is None:
            logger.warning("python-snap7 not available → using PLC simulator")
            use_sim = True
        if use_sim:
            self.client = _SimClient()
        else:
            self.client = snap7.client.Client()  # type: ignore[attr-defined]
        self.connect()

    # ---- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        try:
            if isinstance(self.client, _SimClient):
                self.client.connect()
            else:
                self.client.connect(self.ip, self.rack, self.slot)  # type: ignore[arg-type]
            if not self.client.get_connected():
                raise ConnectionError("Failed to connect to PLC")
            logger.info("PLC connected (%s)", "SIM" if isinstance(self.client, _SimClient) else self.ip)
        except Exception as e:
            # fallback to sim if not already sim
            if not isinstance(self.client, _SimClient):
                logger.exception("PLC connection failed, switching to simulator. Reason: %s", e)
                self.client = _SimClient()
                self.client.connect()
            else:
                raise

    def disconnect(self) -> None:
        if self.client and self.client.get_connected():
            self.client.disconnect()
            logger.info("PLC disconnected")

    # ---- sanitized operations ---------------------------------------------
    def write_payload_to_plc(self, payload: InputPayload) -> None:
        """Write experiment inputs to PLC (DB9) with strong type enforcement."""
        db_number = DB_CONFIG['INPUTS']['TFR']['db_number']

        # TFR (REAL - 4 bytes)
        data = bytearray(4)
        if snap7:
            set_real(data, 0, float(payload.tfr))
        else:
            # pack to IEEE-754 manually (little-endian as snap7.util would do)
            import struct
            data[:] = struct.pack('>f', float(payload.tfr))  # snap7 is big-endian for REAL
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['TFR']['start'], data)

        # FRR (INT - 2 bytes)
        data = bytearray(2)
        if snap7:
            set_int(data, 0, int(payload.frr))
        else:
            import struct
            data[:] = struct.pack('>h', int(payload.frr))  # big-endian 16-bit
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['FRR']['start'], data)

        # TARGET_VOL (REAL)
        data = bytearray(4)
        if snap7:
            set_real(data, 0, float(payload.target_volume))
        else:
            import struct
            data[:] = struct.pack('>f', float(payload.target_volume))
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['TARGET_VOL']['start'], data)

        # TEMP (REAL)
        data = bytearray(4)
        if snap7:
            set_real(data, 0, float(payload.temperature))
        else:
            import struct
            data[:] = struct.pack('>f', float(payload.temperature))
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['TEMP']['start'], data)

        # CHIP_ID (INT) 0=HERRINGBONE, 1=BAFFLE
        chip_val = 0 if payload.chip_id == ChipID.HERRINGBONE else 1
        data = bytearray(2)
        if snap7:
            set_int(data, 0, chip_val)
        else:
            import struct
            data[:] = struct.pack('>h', chip_val)
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['CHIP_ID']['start'], data)

        # MANIFOLD (INT) 1=SMALL, 2=LARGE
        mani_val = 1 if payload.manifold == Manifold.SMALL else 2
        data = bytearray(2)
        if snap7:
            set_int(data, 0, mani_val)
        else:
            import struct
            data[:] = struct.pack('>h', mani_val)
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['MANIFOLD']['start'], data)

        # STATUS (INT) 1=RUN,2=CLEAN,3=PRESSURE_TEST
        mode_map = {Mode.RUN: 1, Mode.CLEAN: 2, Mode.PRESSURE_TEST: 3}
        mode_val = mode_map[payload.mode]
        data = bytearray(2)
        if snap7:
            set_int(data, 0, mode_val)
        else:
            import struct
            data[:] = struct.pack('>h', mode_val)
        self.client.db_write(db_number, DB_CONFIG['INPUTS']['STATUS']['start'], data)

        logger.info("Experiment payload written to PLC DB9 (TFR/FRR/TARGET_VOL/TEMP/CHIP_ID/MANIFOLD/MODE).")

    def read_validation_bit(self) -> bool:
        """Read CRUNCH_VALID bit using bit addressing (e.g., 218.3)."""
        cfg = DB_CONFIG['VALIDATION']['CRUNCH_VALID']
        byte_offset = int(cfg['start'])  # 218 from 218.3
        bit_offset = int((cfg['start'] % 1) * 10)  # 3 from 218.3
        
        result = self.client.db_read(cfg['db_number'], byte_offset, 1)
        if not result:
            return False
            
        # Check specific bit
        return bool(result[0] & (1 << bit_offset))

    def write_command_bit(self, command: str, value: bool) -> None:
        """Write a command bit to the PLC using bit addressing (e.g., 218.0).
        
        For S7-1200, bits in a byte are addressed 0-7, where:
        218.0 = first bit (LSB)
        218.1 = second bit
        218.2 = third bit
        218.3 = fourth bit
        """
        cfg = DB_CONFIG['INPUTS'][command]
        byte_offset = int(cfg['start'])  # 218 from 218.0
        
        # Correct bit offset calculation for S7 addressing
        raw_start = cfg['start']
        if isinstance(raw_start, (int, float)):
            # Convert to string first to avoid floating-point precision issues
            raw_str = f"{raw_start:.1f}"  # Format as "218.1", "218.2", etc.
            parts = raw_str.split('.')
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        else:
            # Handle string format like "218.1"
            parts = str(raw_start).split('.')
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        
        # Validate bit offset
        if not (0 <= bit_offset <= 7):
            raise ValueError(f"Invalid bit offset {bit_offset} for {command}. Must be 0-7.")
        
        # EXTENSIVE DEBUG LOGGING
        logger.info(f"DEBUG: {command} calculation:")
        logger.info(f"  raw_start: {raw_start} (type: {type(raw_start)})")
        logger.info(f"  raw_str: {raw_str if isinstance(raw_start, (int, float)) else 'N/A'}")
        logger.info(f"  parts: {parts}")
        logger.info(f"  bit_offset: {bit_offset}")
        logger.info(f"  byte_offset: {byte_offset}")
        logger.info(f"Writing {command} (value={value}) to DB{cfg['db_number']}.DBX{byte_offset}.{bit_offset} (raw start: {cfg['start']})")
        
        try:
            if isinstance(self.client, _SimClient):
                # For simulator, use bit-level operations
                self.client.db_write_bit(cfg['db_number'], byte_offset, bit_offset, 1 if value else 0)
            else:
                # For real PLC, use snap7's bit operations
                # First read current byte
                result = self.client.db_read(cfg['db_number'], byte_offset, 1)
                current_byte = result[0] if result else 0
                logger.debug(f"Current byte value: 0x{current_byte:02x}")
                
                # Calculate bit mask
                bit_mask = 1 << bit_offset
                logger.debug(f"Bit mask for bit {bit_offset}: 0x{bit_mask:02x}")
                
                # Modify specific bit
                if value:
                    new_byte = current_byte | bit_mask  # Set bit
                else:
                    new_byte = current_byte & ~bit_mask  # Clear bit
                logger.debug(f"New byte value: 0x{new_byte:02x}")
                
                # Write back
                data = bytearray([new_byte])
                self.client.db_write(cfg['db_number'], byte_offset, data)
            
            # Verify write by reading back
            verify = self.read_command_bit(command)
            if verify != value:
                logger.error(f"Bit verification failed for {command}: expected={value}, got={verify}")
                raise ValueError(f"Failed to set {command} bit correctly")
            
            logger.info(f"Successfully wrote and verified {command} bit {bit_offset} = {value}")
            
        except Exception as e:
            logger.error(f"Failed to write {command} bit: {e}", exc_info=True)
            raise

    def read_command_bit(self, command: str) -> bool:
        """Read a command bit from the PLC."""
        cfg = DB_CONFIG['INPUTS'][command]
        byte_offset = int(cfg['start'])
        
        # Correct bit offset calculation for S7 addressing
        raw_start = cfg['start']
        if isinstance(raw_start, (int, float)):
            # Convert to string first to avoid floating-point precision issues
            raw_str = f"{raw_start:.1f}"  # Format as "218.1", "218.2", etc.
            parts = raw_str.split('.')
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        else:
            # Handle string format like "218.1"
            parts = str(raw_start).split('.')
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        
        # Validate bit offset
        if not (0 <= bit_offset <= 7):
            raise ValueError(f"Invalid bit offset {bit_offset} for {command}. Must be 0-7.")
        
        # EXTENSIVE DEBUG LOGGING
        logger.debug(f"DEBUG: {command} calculation:")
        logger.debug(f"  raw_start: {raw_start} (type: {type(raw_start)})")
        logger.debug(f"  raw_str: {raw_str if isinstance(raw_start, (int, float)) else 'N/A'}")
        logger.debug(f"  parts: {parts}")
        logger.debug(f"  bit_offset: {bit_offset}")
        logger.debug(f"  byte_offset: {byte_offset}")
        logger.debug(f"Reading {command} from DB{cfg['db_number']}.DBX{byte_offset}.{bit_offset} (raw start: {cfg['start']})")
        
        try:
            # Read the entire byte
            result = self.client.db_read(cfg['db_number'], byte_offset, 1)
            if not result:
                logger.warning(f"No data read from DB{cfg['db_number']}.DBB{byte_offset}")
                return False
            
            # Extract the specific bit
            current_byte = result[0]
            bit_mask = 1 << bit_offset
            bit_value = bool(current_byte & bit_mask)
            
            logger.debug(f"Read {command} bit {bit_offset} from byte 0x{current_byte:02x} = {bit_value}")
            return bit_value
            
        except Exception as e:
            logger.error(f"Failed to read {command} bit: {e}")
            raise

    def read_status(self) -> int:
        """Read the current machine status."""
        cfg = DB_CONFIG['INPUTS']['STATUS']
        result = self.client.db_read(cfg['db_number'], cfg['start'], 2)  # INT is 2 bytes
        if snap7:
            from snap7.util import get_int
            return get_int(result, 0)
        else:
            import struct
            return struct.unpack('>h', result)[0]  # big-endian 16-bit

# ----------------------------------------------------------------------------
# Simple CLI for quick tests
# ----------------------------------------------------------------------------

def _prompt_choice(title: str, options: list[str]) -> str:
    print(f"{title} ({'/'.join(options)}): ", end='', flush=True)
    while True:
        v = input().strip().upper()
        if v in options:
            return v
        print(f"Please enter one of {options}: ", end='', flush=True)

def demo() -> None:
    """Minimal interactive demo writing inputs & reading validation."""
    print("== TAMARA PLC tool demo (SIM by default) ==")
    simulate = bool(int(os.getenv('PLC_SIM', '1')))  # default simulate ON for safety
    print(f"(Simulation mode: {'ON' if simulate else 'OFF'})")

    plc = PLCInterface(simulate=simulate)
    try:
        # First test command bit writing
        print("\nTesting COMMAND_START bit operations...")
        print("Setting COMMAND_START to TRUE")
        plc.write_command_bit("COMMAND_START", True)
        
        # Read back and verify
        start_bit = plc.read_command_bit("COMMAND_START")
        print(f"Read back COMMAND_START: {start_bit}")
        
        # Now test normal parameter writing
        print("\nNow testing parameter inputs...")
        tfr = float(input("Total Flow Rate (mL/min): ").strip())
        frr = int(input("Flow Rate Ratio (integer): ").strip())
        target_volume = float(input("Target Volume (mL): ").strip())
        temperature = float(input("Temperature (°C): ").strip())
        chip_id = _prompt_choice("Chip ID", ["HERRINGBONE", "BAFFLE"])
        manifold = _prompt_choice("Manifold", ["SMALL", "LARGE"])
        mode = _prompt_choice("Mode", ["RUN", "CLEAN", "PRESSURE_TEST"])

        payload = InputPayload(
            tfr=tfr,
            frr=frr,
            target_volume=target_volume,
            temperature=temperature,
            chip_id=ChipID(chip_id),
            manifold=Manifold(manifold),
            mode=Mode(mode),
        )
        plc.write_payload_to_plc(payload)
        print("Inputs sent. Polling CRUNCH_VALID for 3 seconds ...")
        ok = False
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if plc.read_validation_bit():
                ok = True
                break
            time.sleep(0.1)
        print("Validation:", "ACCEPTED" if ok else "NOT ACCEPTED (or timed out)")
        
        # Test setting COMMAND_START to FALSE
        print("\nSetting COMMAND_START back to FALSE")
        plc.write_command_bit("COMMAND_START", False)
        start_bit = plc.read_command_bit("COMMAND_START")
        print(f"Read back COMMAND_START: {start_bit}")
        
    finally:
        plc.disconnect()

if __name__ == "__main__":
    demo()
