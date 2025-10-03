#!/usr/bin/env python3
"""
plc_tool.py — TAMARA PLC tool interface (standalone)

This module provides a *locked-down* interface to a Siemens S7-1200 PLC used by TAMARA.
It only exposes whitelisted read/write operations for experiment inputs and a single
validation bit. It **does not** expose any APIs to upload/download PLC programs, nor
to browse arbitrary DB memory. This keeps the core PLC IP on-device.

Whitelisted mapping (DB9 = DB_Experiments_):
- TFR (REAL)          → DB9.DBD198
- FRR (INT)           → DB9.DBW202
- TARGET_VOL (REAL)   → DB9.DBD204
- TEMP (REAL)         → DB9.DBD208
- CHIP_ID (INT)       → DB9.DBW212   (0=BAFFLE, 1=HERRINGBONE)
- MANIFOLD (INT)      → DB9.DBW214   (1=SMALL, 2=LARGE)
- STATUS (INT)       → DB9.DBW216   (1=RUN, 2=CLEAN, 3=PRESSURE_TEST)
- COMMAND_START (BOOL)→ DB9.DBB218.0   (1=START, 0=STOP)
- COMMAND_PAUSE_PLAY (BOOL)→ DB9.DBB218.1   (1=PAUSE, 0=PLAY)
- COMMAND_STOP (BOOL) → DB9.DBB218.2   (1=STOP, 0=RUN)
Read-only:
- CRUNCH_VALID (BOOL) → DB9.DBB218.3   (byte read, non-zero means TRUE)

Safeguards
----------
- Only the above DB fields can be read/written via this module.
- If python-snap7 isn't available or a PLC isn't reachable, a safe in-memory simulator
  is used so the code still runs for development and tests.

"""

from __future__ import annotations
import os
import time
import logging
import logging.handlers
from typing import Optional, List, Dict, Any, ContextManager
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from dotenv import load_dotenv

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
# Types and whitelisted mapping. This should match the Text list entries on the PLC
# ----------------------------------------------------------------------------

class OperationMode(IntEnum):
    CONVENTIONAL = 1
    AGENTIC = 2

class MachineMode(IntEnum):
    RUN = 2
    CLEAN = 3
    PRESSURE_TEST = 4

class ChipID(IntEnum):
    BAFFLE = 0
    HERRINGBONE = 1

class ManifoldID(IntEnum):
    SMALL = 0
    LARGE = 1

class OrgSolventID(IntEnum):
    ETHANOL = 0
    IPA = 1
    ACETONE = 2
    METHANOL = 3
    CUSTOM = 4

class ModeCmds(IntEnum):
    START = 0
    PAUSE_PLAY = 1
    CONFIRM = 2
    STOP = 3

@dataclass
class CustomSolvent:
    """Parameters for custom organic solvent"""
    name: str
    viscosity: float  # at 20°C (μPa·s)
    sensitivity: float  # vs. temperature (μPa·s/°C)
    molar_volume: float  # (mL/mol)

@dataclass
class InputPayload:
    """Complete set of user inputs for TAMARA operation"""
    # Core parameters (required, no defaults)
    tfr: float  # Total Flow Rate (mL/min)
    frr: int  # Flow Rate Ratio (integer)
    target_volume: float  # Target Volume (mL)
    temperature: float  # Temperature (°C)
    chip_id: ChipID  # BAFFLE/HERRINGBONE
    manifold_id: ManifoldID  # SMALL/LARGE
    lab_pressure: float  # Lab pressure (mbar)
    org_solvent_id: OrgSolventID  # ETHANOL/IPA/ACETONE/METHANOL/CUSTOM
    
    # Optional parameters (with defaults)
    operation_mode: OperationMode = OperationMode.AGENTIC
    machine_mode: MachineMode = MachineMode.RUN
    custom_solvent: Optional[CustomSolvent] = None  # Required if org_solvent_id == CUSTOM

# PLC DB Constants for DB_Experiments_
DB_CONFIG = {
    'OPERATION': {
        'OPERATION_MODE': {'db_number': 9, 'start': 198, 'type': 'INT'},
        'MACHINE_MODE':   {'db_number': 9, 'start': 200, 'type': 'INT'},
        'CRUNCH_VALID':   {'db_number': 9, 'start': 202.0, 'type': 'BOOL'},
    },
    'INPUTS': {
        'r_TFR':               {'db_number': 9, 'start': 204, 'type': 'REAL'},
        'i_FRR':               {'db_number': 9, 'start': 208, 'type': 'INT'},
        'r_TARGET_VOLUME':     {'db_number': 9, 'start': 210, 'type': 'REAL'},
        'r_TEMPERATURE':       {'db_number': 9, 'start': 214, 'type': 'REAL'},
        'i_CHIP_ID':          {'db_number': 9, 'start': 218, 'type': 'INT'},
        'i_MANIFOLD_ID':      {'db_number': 9, 'start': 220, 'type': 'INT'},
        'i_ORG_SOLVENT_ID':   {'db_number': 9, 'start': 222, 'type': 'INT'},
        's_CUSTOM_ORG_SOLVENT': {'db_number': 9, 'start': 224, 'type': 'STRING', 'length': 16},
        'r_LAB_PRESSURE':     {'db_number': 9, 'start': 242, 'type': 'REAL'},
    },
    'CUSTOM_SOLVENT': {
        'r_VISCOSITY':        {'db_number': 9, 'start': 246, 'type': 'REAL'},
        'r_SENSITIVITY':      {'db_number': 9, 'start': 250, 'type': 'REAL'},
        'r_MOLAR_VOLUME':     {'db_number': 9, 'start': 254, 'type': 'REAL'},
    },
    'COMMANDS_RUN': {
        'b_START':      {'db_number': 9, 'start': 258.0, 'type': 'BOOL'},
        'b_PAUSE_PLAY': {'db_number': 9, 'start': 258.1, 'type': 'BOOL'},
        'b_CONFIRM':    {'db_number': 9, 'start': 258.2, 'type': 'BOOL'},
        'b_STOP':       {'db_number': 9, 'start': 258.3, 'type': 'BOOL'},
    },
    'COMMANDS_CLEAN': {
        'b_START':      {'db_number': 9, 'start': 260.0, 'type': 'BOOL'},
        'b_PAUSE_PLAY': {'db_number': 9, 'start': 260.1, 'type': 'BOOL'},
        'b_CONFIRM':    {'db_number': 9, 'start': 260.2, 'type': 'BOOL'},
        'b_STOP':       {'db_number': 9, 'start': 260.3, 'type': 'BOOL'},
    },
    'COMMANDS_PRESSURE_TEST': {
        'b_START':      {'db_number': 9, 'start': 262.0, 'type': 'BOOL'},
        'b_PAUSE_PLAY': {'db_number': 9, 'start': 262.1, 'type': 'BOOL'},
        'b_CONFIRM':    {'db_number': 9, 'start': 262.2, 'type': 'BOOL'},
        'b_STOP':       {'db_number': 9, 'start': 262.3, 'type': 'BOOL'},
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

class PLCTransaction:
    """Context manager for batching PLC writes with verification.
    
    Usage:
        with plc.transaction() as tx:
            tx.write_real('r_TFR', 1.23)
            tx.write_int('i_FRR', 5)
            # ... more writes ...
            # All writes are verified and committed at context exit
            # If any verification fails, all changes are rolled back
    """
    def __init__(self, plc: PLCInterface):
        self.plc = plc
        self.writes: List[Dict[str, Any]] = []
        self.committed = False
        
    def write_real(self, tag: str, value: float) -> None:
        """Queue a REAL write."""
        self.writes.append({
            'type': 'REAL',
            'tag': tag,
            'value': float(value)
        })
        
    def write_int(self, tag: str, value: int) -> None:
        """Queue an INT write."""
        self.writes.append({
            'type': 'INT',
            'tag': tag,
            'value': int(value)
        })
        
    def write_bool(self, tag: str, value: bool) -> None:
        """Queue a BOOL write."""
        self.writes.append({
            'type': 'BOOL',
            'tag': tag,
            'value': bool(value)
        })
        
    def write_string(self, tag: str, value: str, max_len: int) -> None:
        """Queue a STRING write."""
        if len(value) > max_len:
            raise ValueError(f"String '{value}' exceeds max length {max_len}")
        self.writes.append({
            'type': 'STRING',
            'tag': tag,
            'value': value,
            'max_len': max_len
        })
    
    def commit(self) -> None:
        """Execute all queued writes with verification."""
        if self.committed:
            return
            
        errors = []
        try:
            # Execute all writes
            for write in self.writes:
                if write['type'] == 'REAL':
                    self.plc._write_real(write['tag'], write['value'])
                elif write['type'] == 'INT':
                    self.plc._write_int(write['tag'], write['value'])
                elif write['type'] == 'BOOL':
                    self.plc._write_bool(write['tag'], write['value'])
                elif write['type'] == 'STRING':
                    self.plc._write_string(write['tag'], write['value'], write['max_len'])
                    
            # Verify all writes
            for write in self.writes:
                if write['type'] == 'REAL':
                    actual = self.plc._read_real(write['tag'])
                    if abs(actual - write['value']) > 1e-6:
                        errors.append(f"Verification failed for {write['tag']}: expected {write['value']}, got {actual}")
                elif write['type'] == 'INT':
                    actual = self.plc._read_int(write['tag'])
                    if actual != write['value']:
                        errors.append(f"Verification failed for {write['tag']}: expected {write['value']}, got {actual}")
                elif write['type'] == 'BOOL':
                    actual = self.plc._read_bool(write['tag'])
                    if actual != write['value']:
                        errors.append(f"Verification failed for {write['tag']}: expected {write['value']}, got {actual}")
                elif write['type'] == 'STRING':
                    actual = self.plc._read_string(write['tag'])
                    if actual != write['value']:
                        errors.append(f"Verification failed for {write['tag']}: expected {write['value']}, got {actual}")
                        
            if errors:
                raise ValueError("Transaction verification failed:\n" + "\n".join(errors))
                
            self.committed = True
            
        except Exception as e:
            # On any error, try to roll back by clearing all written values
            rollback_errors = []
            for write in self.writes:
                try:
                    if write['type'] == 'REAL':
                        self.plc._write_real(write['tag'], 0.0)
                        # Verify rollback
                        if abs(self.plc._read_real(write['tag'])) > 1e-6:
                            rollback_errors.append(f"Failed to rollback {write['tag']} to 0.0")
                    elif write['type'] == 'INT':
                        self.plc._write_int(write['tag'], 0)
                        # Verify rollback
                        if self.plc._read_int(write['tag']) != 0:
                            rollback_errors.append(f"Failed to rollback {write['tag']} to 0")
                    elif write['type'] == 'BOOL':
                        self.plc._write_bool(write['tag'], False)
                        # Verify rollback
                        if self.plc._read_bool(write['tag']):
                            rollback_errors.append(f"Failed to rollback {write['tag']} to False")
                    elif write['type'] == 'STRING':
                        self.plc._write_string(write['tag'], "", write['max_len'])
                        # Verify rollback
                        if self.plc._read_string(write['tag']) != "":
                            rollback_errors.append(f"Failed to rollback {write['tag']} to empty string")
                except Exception as rollback_error:
                    rollback_errors.append(f"Error during rollback of {write['tag']}: {str(rollback_error)}")
                    logger.error(f"Rollback error for {write['tag']}: {rollback_error}", exc_info=True)
            
            if rollback_errors:
                error_msg = f"Transaction failed: {str(e)}\nRollback errors:\n" + "\n".join(rollback_errors)
                logger.error(error_msg)
                raise ValueError(error_msg)
            else:
                logger.info("Transaction failed but rollback successful")
                raise ValueError(f"Transaction failed and rolled back successfully: {str(e)}")

class PLCInterface:
    """Locked-down PLC interface for TAMARA."""
    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False  # Don't suppress exceptions
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

    def _write_real(self, tag: str, value: float) -> None:
        """Write a REAL value to PLC."""
        section = None
        for s in ['OPERATION', 'INPUTS', 'CUSTOM_SOLVENT']:
            if tag in DB_CONFIG[s]:
                section = s
                break
        if not section:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG[section][tag]
        data = bytearray(4)
        if snap7:
            set_real(data, 0, float(value))
        else:
            import struct
            data[:] = struct.pack('>f', float(value))  # big-endian for S7
        self.client.db_write(cfg['db_number'], cfg['start'], data)

    def _read_real(self, tag: str) -> float:
        """Read a REAL value from PLC."""
        section = None
        for s in ['OPERATION', 'INPUTS', 'CUSTOM_SOLVENT']:
            if tag in DB_CONFIG[s]:
                section = s
                break
        if not section:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG[section][tag]
        result = self.client.db_read(cfg['db_number'], cfg['start'], 4)
        if snap7:
            from snap7.util import get_real
            return get_real(result, 0)
        else:
            import struct
            return struct.unpack('>f', result)[0]  # big-endian for S7

    def _write_int(self, tag: str, value: int) -> None:
        """Write an INT value to PLC."""
        section = None
        for s in ['OPERATION', 'INPUTS']:
            if tag in DB_CONFIG[s]:
                section = s
                break
        if not section:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG[section][tag]
        data = bytearray(2)
        if snap7:
            set_int(data, 0, int(value))
        else:
            import struct
            data[:] = struct.pack('>h', int(value))  # big-endian for S7
        self.client.db_write(cfg['db_number'], cfg['start'], data)

    def _read_int(self, tag: str) -> int:
        """Read an INT value from PLC."""
        section = None
        for s in ['OPERATION', 'INPUTS']:
            if tag in DB_CONFIG[s]:
                section = s
                break
        if not section:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG[section][tag]
        result = self.client.db_read(cfg['db_number'], cfg['start'], 2)
        if snap7:
            from snap7.util import get_int
            return get_int(result, 0)
        else:
            import struct
            return struct.unpack('>h', result)[0]  # big-endian for S7

    def _write_bool(self, tag: str, value: bool) -> None:
        """Write a BOOL value to PLC.
        
        Args:
            tag: Either a direct tag name from DB_CONFIG or section.tag format
                (e.g., 'CRUNCH_VALID' or 'COMMANDS_RUN.b_START')
            value: Boolean value to write
        """
        # Handle section.tag format
        if '.' in tag:
            section, subtag = tag.split('.')
            if section not in DB_CONFIG or subtag not in DB_CONFIG[section]:
                raise ValueError(f"Unknown tag: {tag}")
            cfg = DB_CONFIG[section][subtag]
        else:
            # Direct tag lookup
            section = None
            for s in ['OPERATION', 'COMMANDS_RUN', 'COMMANDS_CLEAN', 'COMMANDS_PRESSURE_TEST']:
                if tag in DB_CONFIG[s]:
                    section = s
                    break
            if not section:
                raise ValueError(f"Unknown tag: {tag}")
            cfg = DB_CONFIG[section][tag]
        byte_offset = int(cfg['start'])
        bit_offset = int((cfg['start'] % 1) * 10)
        
        # EXTENSIVE DEBUG LOGGING
        logger.info(f"Writing BOOL {tag} = {value}")
        logger.info(f"  section: {section}")
        logger.info(f"  byte_offset: {byte_offset}")
        logger.info(f"  bit_offset: {bit_offset}")
        logger.info(f"  raw_start: {cfg['start']}")
        
        try:
            if isinstance(self.client, _SimClient):
                self.client.db_write_bit(cfg['db_number'], byte_offset, bit_offset, 1 if value else 0)
            else:
                # Read current byte
                result = self.client.db_read(cfg['db_number'], byte_offset, 1)
                current_byte = result[0] if result else 0
                logger.debug(f"Current byte value: 0x{current_byte:02x}")
                
                # Calculate bit mask
                bit_mask = 1 << bit_offset
                logger.debug(f"Bit mask for bit {bit_offset}: 0x{bit_mask:02x}")
                
                # Modify bit
                if value:
                    new_byte = current_byte | bit_mask  # Set bit
                else:
                    new_byte = current_byte & ~bit_mask  # Clear bit
                logger.debug(f"New byte value: 0x{new_byte:02x}")
                
                # Write back
                data = bytearray([new_byte])
                self.client.db_write(cfg['db_number'], byte_offset, data)
            
            logger.info(f"Successfully wrote {tag} = {value}")
            
        except Exception as e:
            logger.error(f"Failed to write {tag} = {value}: {e}", exc_info=True)
            raise

    def _read_bool(self, tag: str) -> bool:
        """Read a BOOL value from PLC.
        
        Args:
            tag: Either a direct tag name from DB_CONFIG or section.tag format
                (e.g., 'CRUNCH_VALID' or 'COMMANDS_RUN.b_START')
        """
        # Handle section.tag format
        if '.' in tag:
            section, subtag = tag.split('.')
            if section not in DB_CONFIG or subtag not in DB_CONFIG[section]:
                raise ValueError(f"Unknown tag: {tag}")
            cfg = DB_CONFIG[section][subtag]
        else:
            # Direct tag lookup
            section = None
            for s in ['OPERATION', 'COMMANDS_RUN', 'COMMANDS_CLEAN', 'COMMANDS_PRESSURE_TEST']:
                if tag in DB_CONFIG[s]:
                    section = s
                    break
            if not section:
                raise ValueError(f"Unknown tag: {tag}")
            cfg = DB_CONFIG[section][tag]
        byte_offset = int(cfg['start'])
        bit_offset = int((cfg['start'] % 1) * 10)
        
        if isinstance(self.client, _SimClient):
            return self.client.db_read_bit(cfg['db_number'], byte_offset, bit_offset)
        else:
            result = self.client.db_read(cfg['db_number'], byte_offset, 1)
            if not result:
                return False
            return bool(result[0] & (1 << bit_offset))

    def _write_string(self, tag: str, value: str, max_len: int) -> None:
        """Write a STRING value to PLC."""
        if tag not in DB_CONFIG['INPUTS']:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG['INPUTS'][tag]
        if cfg['type'] != 'STRING':
            raise ValueError(f"Tag {tag} is not a STRING")
            
        # Ensure string fits
        if len(value) > max_len:
            raise ValueError(f"String '{value}' exceeds max length {max_len}")
            
        # S7 STRING format:
        # Byte 0: Maximum length (max_len)
        # Byte 1: Actual length (len(value))
        # Bytes 2..N: String data (padded with nulls)
        data = bytearray(2 + max_len)  # Header + data
        data[0] = max_len
        data[1] = len(value)
        data[2:2+len(value)] = value.encode('utf-8')
        
        self.client.db_write(cfg['db_number'], cfg['start'], data)

    def _read_string(self, tag: str) -> str:
        """Read a STRING value from PLC."""
        if tag not in DB_CONFIG['INPUTS']:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG['INPUTS'][tag]
        if cfg['type'] != 'STRING':
            raise ValueError(f"Tag {tag} is not a STRING")
            
        # Read header first to get actual length
        header = self.client.db_read(cfg['db_number'], cfg['start'], 2)
        max_len = header[0]
        actual_len = header[1]
        
        # Read string data
        if actual_len > 0:
            data = self.client.db_read(cfg['db_number'], cfg['start'] + 2, actual_len)
            return data.decode('utf-8')
        return ""

    @contextmanager
    def transaction(self) -> ContextManager[PLCTransaction]:
        """Create a transaction for batched writes with verification.
        
        Usage:
            with plc.transaction() as tx:
                tx.write_real('r_TFR', 1.23)
                tx.write_int('i_FRR', 5)
                # ... more writes ...
                # All writes are verified and committed at context exit
        """
        tx = PLCTransaction(self)
        try:
            yield tx
            tx.commit()
        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            raise

    # ---- sanitized operations ---------------------------------------------
    def write_parameters_to_plc(self, payload: InputPayload) -> None:
        """Write experiment parameters to PLC (DB9) without setting machine mode or commands.
        
        This function only writes the operational parameters and operation mode,
        but does NOT set the machine mode or any command bits. This allows
        parameters to be validated by the PLC before the operation is started.
        """
        with self.transaction() as tx:
            # Operation mode only (not machine mode)
            tx.write_int('OPERATION_MODE', int(payload.operation_mode))
            
            # Core parameters
            tx.write_real('r_TFR', float(payload.tfr))
            tx.write_int('i_FRR', int(payload.frr))
            tx.write_real('r_TARGET_VOLUME', float(payload.target_volume))
            tx.write_real('r_TEMPERATURE', float(payload.temperature))
            tx.write_int('i_CHIP_ID', int(payload.chip_id))
            tx.write_int('i_MANIFOLD_ID', int(payload.manifold_id))
            tx.write_real('r_LAB_PRESSURE', float(payload.lab_pressure))
            
            # Solvent handling
            tx.write_int('i_ORG_SOLVENT_ID', int(payload.org_solvent_id))
            
            if payload.org_solvent_id == OrgSolventID.CUSTOM:
                if not payload.custom_solvent:
                    raise ValueError("Custom solvent parameters required when org_solvent_id is CUSTOM")
                    
                # Write custom solvent name (S7 STRING[16])
                tx.write_string('s_CUSTOM_ORG_SOLVENT', payload.custom_solvent.name, 16)
                
                # Write custom solvent parameters
                tx.write_real('r_VISCOSITY', float(payload.custom_solvent.viscosity))
                tx.write_real('r_SENSITIVITY', float(payload.custom_solvent.sensitivity))
                tx.write_real('r_MOLAR_VOLUME', float(payload.custom_solvent.molar_volume))
            else:
                # Clear custom fields when using a preset solvent
                tx.write_string('s_CUSTOM_ORG_SOLVENT', "", 16)
                tx.write_real('r_VISCOSITY', 0.0)
                tx.write_real('r_SENSITIVITY', 0.0)
                tx.write_real('r_MOLAR_VOLUME', 0.0)
            
        logger.info(
            "Experiment parameters written to PLC DB9 (no machine mode set):\n"
            f"- Operation: {payload.operation_mode.name}\n"
            f"- Core params: TFR={payload.tfr}, FRR={payload.frr}, Vol={payload.target_volume}, "
            f"Temp={payload.temperature}, Chip={payload.chip_id.name}, Manifold={payload.manifold_id.name}\n"
            f"- Solvent: {payload.org_solvent_id.name}"
            + (f" ({payload.custom_solvent.name})" if payload.org_solvent_id == OrgSolventID.CUSTOM else "")
        )

    def write_payload_to_plc(self, payload: InputPayload) -> None:
        """Write complete experiment payload to PLC (DB9) with machine mode and commands.
        
        This function writes all parameters AND sets the machine mode.
        Use write_parameters_to_plc() first for parameter validation.
        """
        with self.transaction() as tx:
            # Operation mode and machine mode
            tx.write_int('OPERATION_MODE', int(payload.operation_mode))
            tx.write_int('MACHINE_MODE', int(payload.machine_mode))
            
            # Core parameters
            tx.write_real('r_TFR', float(payload.tfr))
            tx.write_int('i_FRR', int(payload.frr))
            tx.write_real('r_TARGET_VOLUME', float(payload.target_volume))
            tx.write_real('r_TEMPERATURE', float(payload.temperature))
            tx.write_int('i_CHIP_ID', int(payload.chip_id))
            tx.write_int('i_MANIFOLD_ID', int(payload.manifold_id))
            tx.write_real('r_LAB_PRESSURE', float(payload.lab_pressure))
            
            # Solvent handling
            tx.write_int('i_ORG_SOLVENT_ID', int(payload.org_solvent_id))
            
            if payload.org_solvent_id == OrgSolventID.CUSTOM:
                if not payload.custom_solvent:
                    raise ValueError("Custom solvent parameters required when org_solvent_id is CUSTOM")
                    
                # Write custom solvent name (S7 STRING[16])
                tx.write_string('s_CUSTOM_ORG_SOLVENT', payload.custom_solvent.name, 16)
                
                # Write custom solvent parameters
                tx.write_real('r_VISCOSITY', float(payload.custom_solvent.viscosity))
                tx.write_real('r_SENSITIVITY', float(payload.custom_solvent.sensitivity))
                tx.write_real('r_MOLAR_VOLUME', float(payload.custom_solvent.molar_volume))
            else:
                # Clear custom fields when using a preset solvent
                tx.write_string('s_CUSTOM_ORG_SOLVENT', "", 16)
                tx.write_real('r_VISCOSITY', 0.0)
                tx.write_real('r_SENSITIVITY', 0.0)
                tx.write_real('r_MOLAR_VOLUME', 0.0)
            
        logger.info(
            "Complete experiment payload written to PLC DB9:\n"
            f"- Operation: {payload.operation_mode.name}, Machine: {payload.machine_mode.name}\n"
            f"- Core params: TFR={payload.tfr}, FRR={payload.frr}, Vol={payload.target_volume}, "
            f"Temp={payload.temperature}, Chip={payload.chip_id.name}, Manifold={payload.manifold_id.name}\n"
            f"- Solvent: {payload.org_solvent_id.name}"
            + (f" ({payload.custom_solvent.name})" if payload.org_solvent_id == OrgSolventID.CUSTOM else "")
        )

    def read_crunch_valid(self) -> bool:
        """Read Crunch_Valid bit (DBX202.0)."""
        cfg = DB_CONFIG['OPERATION']['CRUNCH_VALID']
        byte_offset = int(cfg['start'])  # 202 from 202.0
        bit_offset = int((cfg['start'] % 1) * 10)  # 0 from 202.0
        
        result = self.client.db_read(cfg['db_number'], byte_offset, 1)
        if not result:
            return False
            
        # Check specific bit
        return bool(result[0] & (1 << bit_offset))

    def clear_all_cmd_bits(self) -> None:
        """Clear all command bits across all modes."""
        logger.info("Clearing all command bits")
        for mode_key in ['COMMANDS_RUN', 'COMMANDS_CLEAN', 'COMMANDS_PRESSURE_TEST']:
            for cmd_key in ['b_START', 'b_PAUSE_PLAY', 'b_CONFIRM', 'b_STOP']:
                tag = f"{mode_key}.{cmd_key}"
                self._write_bool(tag, False)
                
                # Verify
                if self._read_bool(tag):
                    raise ValueError(f"Failed to clear {tag}")
        logger.info("All command bits cleared and verified")

    def pulse_cmd(self, mode: MachineMode, cmd: ModeCmds, value: bool = True) -> None:
        """Set a command bit for a specific mode, enforcing exclusivity rules.
        
        Args:
            mode: Target machine mode (RUN/CLEAN/PRESSURE_TEST)
            cmd: Command to set (START/PAUSE_PLAY/CONFIRM/STOP)
            value: True to set, False to clear
            
        Rules:
        - Setting START in any mode clears START in other modes
        - Setting STOP clears START/PAUSE_PLAY/CONFIRM in that mode
        - All writes are verified
        """
        mode_map = {
            MachineMode.RUN: 'COMMANDS_RUN',
            MachineMode.CLEAN: 'COMMANDS_CLEAN',
            MachineMode.PRESSURE_TEST: 'COMMANDS_PRESSURE_TEST'
        }
        cmd_map = {
            ModeCmds.START: 'b_START',
            ModeCmds.PAUSE_PLAY: 'b_PAUSE_PLAY',
            ModeCmds.CONFIRM: 'b_CONFIRM',
            ModeCmds.STOP: 'b_STOP'
        }
        
        mode_key = mode_map[mode]
        cmd_key = cmd_map[cmd]
        target_tag = f"{mode_key}.{cmd_key}"
        
        logger.info(f"Pulsing {target_tag} to {value}")
        
        # Handle exclusivity rules
        if cmd == ModeCmds.START and value:
            # Clear START in other modes
            for other_mode in mode_map.values():
                if other_mode != mode_key:
                    self._write_bool(f"{other_mode}.b_START", False)
                    
        elif cmd == ModeCmds.STOP and value:
            # Clear all bits in this mode
            for other_cmd in ['b_START', 'b_PAUSE_PLAY', 'b_CONFIRM']:
                self._write_bool(f"{mode_key}.{other_cmd}", False)
        
        # Set the requested bit
        self._write_bool(target_tag, value)
        
        # Verify all changes
        if self._read_bool(target_tag) != value:
            raise ValueError(f"Failed to set {target_tag} to {value}")
            
        logger.info(f"Command {target_tag} successfully set to {value} and verified")

    def _get_command_tag(self, mode_key: str, cmd_key: str) -> str:
        """Convert mode and command keys to a DB tag."""
        if mode_key not in ['COMMANDS_RUN', 'COMMANDS_CLEAN', 'COMMANDS_PRESSURE_TEST']:
            raise ValueError(f"Invalid mode key: {mode_key}")
        if cmd_key not in ['b_START', 'b_PAUSE_PLAY', 'b_CONFIRM', 'b_STOP']:
            raise ValueError(f"Invalid command key: {cmd_key}")
        return f"{mode_key}.{cmd_key}"

    def _read_int(self, tag: str) -> int:
        """Read an INT value from PLC."""
        section = None
        for s in ['OPERATION', 'INPUTS']:
            if tag in DB_CONFIG[s]:
                section = s
                break
        if not section:
            raise ValueError(f"Unknown tag: {tag}")
            
        cfg = DB_CONFIG[section][tag]
        result = self.client.db_read(cfg['db_number'], cfg['start'], 2)  # INT is 2 bytes
        if isinstance(self.client, _SimClient):
            # For simulator, convert bytes to bytearray for mutability
            result = bytearray(result)
        if snap7:
            from snap7.util import get_int
            return get_int(result, 0)
        else:
            import struct
            return struct.unpack('>h', result)[0]  # big-endian 16-bit

    def read_operation_mode(self) -> OperationMode:
        """Read the current operation mode (CONVENTIONAL/AGENTIC)."""
        mode = self._read_int('OPERATION_MODE')
        try:
            return OperationMode(mode)
        except ValueError:
            raise ValueError(f"Invalid operation mode value: {mode}")

    def read_status(self) -> int:
        """Read the current machine status (MachineMode)."""
        return self._read_int('MACHINE_MODE')
        
    def set_machine_mode(self, mode: int) -> None:
        """Set the machine mode (status).
        
        Args:
            mode: Status code to set (e.g., 1 for READY)
        """
        with self.transaction() as tx:
            tx.write_int('MACHINE_MODE', mode)
        logger.info(f"Machine mode set to {mode}")

    def start_operation(self, payload: InputPayload) -> None:
        """Start an operation by setting machine mode and command bits.
        
        This function should only be called after user confirmation.
        It sets the machine mode and the START command bit for the operation.
        
        Args:
            payload: The validated operation parameters
        """
        with self.transaction() as tx:
            # Set machine mode
            tx.write_int('MACHINE_MODE', int(payload.machine_mode))
            
            # Clear all command bits first
            self.clear_all_cmd_bits()
            
            # Set START bit for the appropriate mode
            mode_map = {
                MachineMode.RUN: 'COMMANDS_RUN',
                MachineMode.CLEAN: 'COMMANDS_CLEAN', 
                MachineMode.PRESSURE_TEST: 'COMMANDS_PRESSURE_TEST'
            }
            mode_key = mode_map[payload.machine_mode]
            self._write_bool(f"{mode_key}.b_START", True)
            
        logger.info(f"Operation started: {payload.machine_mode.name} mode with START bit set")

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
        # First test command bit operations
        print("\nTesting RUN mode START command...")
        print("Setting RUN.START to TRUE")
        plc.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        
        # Now test normal parameter writing
        print("\nNow testing parameter inputs...")
        tfr = float(input("Total Flow Rate (mL/min): ").strip())
        frr = int(input("Flow Rate Ratio (integer): ").strip())
        target_volume = float(input("Target Volume (mL): ").strip())
        temperature = float(input("Temperature (°C): ").strip())
        lab_pressure = float(input("Lab pressure (mbar): ").strip())
        
        chip_id = _prompt_choice("Chip ID", ["BAFFLE", "HERRINGBONE"])
        manifold = _prompt_choice("Manifold", ["SMALL", "LARGE"])
        solvent = _prompt_choice("Solvent", ["ETHANOL", "IPA", "ACETONE", "METHANOL", "CUSTOM"])
        
        # Handle custom solvent if selected
        custom_solvent = None
        if solvent == "CUSTOM":
            name = input("Custom solvent name: ").strip()
            if len(name) > 16:
                raise ValueError("Custom solvent name must be 16 characters or less")
            viscosity = float(input("Viscosity at 20°C (μPa·s): ").strip())
            sensitivity = float(input("Temperature sensitivity (μPa·s/°C): ").strip())
            molar_volume = float(input("Molar volume (mL/mol): ").strip())
            custom_solvent = CustomSolvent(
                name=name,
                viscosity=viscosity,
                sensitivity=sensitivity,
                molar_volume=molar_volume
            )

        # Create payload with all parameters
        payload = InputPayload(
            # Core parameters (required)
            tfr=tfr,
            frr=frr,
            target_volume=target_volume,
            temperature=temperature,
            chip_id=ChipID[chip_id],
            manifold_id=ManifoldID[manifold],
            lab_pressure=lab_pressure,
            org_solvent_id=OrgSolventID[solvent],
            
            # Optional parameters
            operation_mode=OperationMode.AGENTIC,
            machine_mode=MachineMode.RUN,
            custom_solvent=custom_solvent
        )
        
        # Write payload and check validation
        plc.write_payload_to_plc(payload)
        print("Inputs sent. Polling CRUNCH_VALID for 3 seconds ...")
        ok = False
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if plc.read_crunch_valid():
                ok = True
                break
            time.sleep(0.1)
        print("Validation:", "ACCEPTED" if ok else "NOT ACCEPTED (or timed out)")
        
        # Test command sequence
        if ok:
            print("\nTesting command sequence...")
            print("1. Setting RUN.CONFIRM")
            plc.pulse_cmd(MachineMode.RUN, ModeCmds.CONFIRM, True)
            
            print("2. Setting RUN.PAUSE_PLAY")
            plc.pulse_cmd(MachineMode.RUN, ModeCmds.PAUSE_PLAY, True)
            time.sleep(1)  # Simulate pause
            
            print("3. Clearing RUN.PAUSE_PLAY")
            plc.pulse_cmd(MachineMode.RUN, ModeCmds.PAUSE_PLAY, False)
            
            print("4. Setting RUN.STOP")
            plc.pulse_cmd(MachineMode.RUN, ModeCmds.STOP, True)
        
    finally:
        plc.disconnect()

if __name__ == "__main__":
    demo()
