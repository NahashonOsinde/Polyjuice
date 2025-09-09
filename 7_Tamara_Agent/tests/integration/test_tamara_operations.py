"""
Integration tests for TAMARA operations.
Tests the interaction between PLCInterface and the agent's state management.
"""
import pytest
import time
from plc_tool import PLCInterface, InputPayload
from plc_tool import OperationMode, MachineMode, ChipID, ManifoldID, OrgSolventID, ModeCmds
from tamara_graph import GraphState, check_operation_mode, ensure_ready_state

def test_operation_mode_transition(plc_sim):
    """Test operation mode checking and transition."""
    with plc_sim:
        # Set CONVENTIONAL mode
        plc_sim._write_int('OPERATION_MODE', int(OperationMode.CONVENTIONAL))
        assert not check_operation_mode()
        
        # Set AGENTIC mode
        plc_sim._write_int('OPERATION_MODE', int(OperationMode.AGENTIC))
        assert check_operation_mode()

def test_ready_state_transition(plc_sim):
    """Test transition to READY state."""
    with plc_sim:
        # Set some non-READY state
        plc_sim._write_int('MACHINE_MODE', 2)  # RUN mode
        
        # Transition to READY
        ensure_ready_state()
        
        # Verify state
        assert plc_sim._read_int('MACHINE_MODE') == 1  # READY state

def test_run_operation_flow(plc_sim, sample_payload):
    """Test complete RUN operation flow."""
    with plc_sim:
        # 1. Set AGENTIC mode
        plc_sim._write_int('OPERATION_MODE', int(OperationMode.AGENTIC))
        
        # 2. Ensure READY state
        ensure_ready_state()
        
        # 3. Write payload
        plc_sim.write_payload_to_plc(sample_payload)
        
        # 4. Set Crunch_Valid to simulate PLC validation
        plc_sim._write_bool('CRUNCH_VALID', True)
        
        # 5. Clear command bits
        plc_sim.clear_all_cmd_bits()
        
        # 6. Start RUN operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        
        # Verify command bits
        assert plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_PAUSE_PLAY')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_CONFIRM')

def test_pause_resume_flow(plc_sim):
    """Test pause and resume operation flow."""
    with plc_sim:
        # 1. Start RUN operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        
        # 2. Pause operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.PAUSE_PLAY, True)
        assert plc_sim._read_bool('COMMANDS_RUN.b_PAUSE_PLAY')
        
        # 3. Resume operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.PAUSE_PLAY, False)
        assert not plc_sim._read_bool('COMMANDS_RUN.b_PAUSE_PLAY')

def test_stop_operation_flow(plc_sim):
    """Test stop operation flow."""
    with plc_sim:
        # 1. Start RUN operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.CONFIRM, True)
        
        # 2. Stop operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.STOP, True)
        
        # Verify all bits cleared
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_PAUSE_PLAY')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_CONFIRM')
        assert plc_sim._read_bool('COMMANDS_RUN.b_STOP')

def test_mode_transition_safety(plc_sim):
    """Test safety of mode transitions."""
    with plc_sim:
        # 1. Start RUN operation
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        
        # 2. Try to start CLEAN while RUN is active
        plc_sim.pulse_cmd(MachineMode.CLEAN, ModeCmds.START, True)
        
        # Verify RUN was stopped
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert plc_sim._read_bool('COMMANDS_CLEAN.b_START')

def test_crunch_validation_timeout(plc_sim, sample_payload):
    """Test handling of Crunch validation timeout."""
    with plc_sim:
        # Write payload but don't set Crunch_Valid
        plc_sim.write_payload_to_plc(sample_payload)
        
        # Try to read Crunch_Valid multiple times
        timeout = 3.0
        interval = 0.1
        valid = False
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if plc_sim.read_crunch_valid():
                valid = True
                break
            time.sleep(interval)
        
        assert not valid  # Should timeout without validation

def test_error_recovery(plc_sim):
    """Test error recovery procedures."""
    with plc_sim:
        # 1. Simulate error state
        plc_sim._write_int('MACHINE_MODE', 6)  # FAULTED state
        
        # 2. Recover to READY state
        ensure_ready_state()
        
        # 3. Verify recovery
        assert plc_sim._read_int('MACHINE_MODE') == 1  # READY state
        
        # 4. Verify all command bits cleared
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert not plc_sim._read_bool('COMMANDS_CLEAN.b_START')
        assert not plc_sim._read_bool('COMMANDS_PRESSURE_TEST.b_START')
