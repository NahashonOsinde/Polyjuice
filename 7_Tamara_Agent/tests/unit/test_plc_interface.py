"""
Unit tests for PLCInterface class.
"""
import pytest
from plc_tool import PLCInterface, InputPayload, CustomSolvent
from plc_tool import OperationMode, MachineMode, ChipID, ManifoldID, OrgSolventID

def test_plc_connection(plc_sim):
    """Test basic PLC connection and disconnection."""
    assert plc_sim.client.get_connected()
    plc_sim.disconnect()
    assert not plc_sim.client.get_connected()

def test_write_read_real(plc_sim):
    """Test writing and reading REAL values."""
    with plc_sim:
        plc_sim._write_real('r_TFR', 1.23)
        assert abs(plc_sim._read_real('r_TFR') - 1.23) < 1e-6

def test_write_read_int(plc_sim):
    """Test writing and reading INT values."""
    with plc_sim:
        plc_sim._write_int('i_FRR', 42)
        assert plc_sim._read_int('i_FRR') == 42

def test_write_read_bool(plc_sim):
    """Test writing and reading BOOL values."""
    with plc_sim:
        plc_sim._write_bool('COMMANDS_RUN.b_START', True)
        assert plc_sim._read_bool('COMMANDS_RUN.b_START')
        plc_sim._write_bool('COMMANDS_RUN.b_START', False)
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')

def test_write_read_string(plc_sim):
    """Test writing and reading STRING values."""
    with plc_sim:
        test_str = "test123"
        plc_sim._write_string('s_CUSTOM_ORG_SOLVENT', test_str, 16)
        assert plc_sim._read_string('s_CUSTOM_ORG_SOLVENT') == test_str

def test_transaction_commit(plc_sim):
    """Test successful transaction commit."""
    with plc_sim:
        with plc_sim.transaction() as tx:
            tx.write_real('r_TFR', 1.23)
            tx.write_int('i_FRR', 42)
            tx.write_bool('COMMANDS_RUN.b_START', True)
        
        # Verify all writes were committed
        assert abs(plc_sim._read_real('r_TFR') - 1.23) < 1e-6
        assert plc_sim._read_int('i_FRR') == 42
        assert plc_sim._read_bool('COMMANDS_RUN.b_START')

def test_transaction_rollback(plc_sim):
    """Test transaction rollback on error."""
    with plc_sim:
        # Write initial values
        with plc_sim.transaction() as tx:
            tx.write_real('r_TFR', 1.0)
            tx.write_int('i_FRR', 1)
        
        # Try a transaction that will fail
        with pytest.raises(ValueError):
            with plc_sim.transaction() as tx:
                tx.write_real('r_TFR', 2.0)
                tx.write_int('INVALID_TAG', 42)  # This will fail
        
        # Verify original values were preserved
        assert abs(plc_sim._read_real('r_TFR') - 1.0) < 1e-6
        assert plc_sim._read_int('i_FRR') == 1

def test_write_payload(plc_sim, sample_payload):
    """Test writing a complete payload."""
    with plc_sim:
        plc_sim.write_payload_to_plc(sample_payload)
        
        # Verify core parameters
        assert abs(plc_sim._read_real('r_TFR') - sample_payload.tfr) < 1e-6
        assert plc_sim._read_int('i_FRR') == sample_payload.frr
        assert plc_sim._read_int('i_CHIP_ID') == int(sample_payload.chip_id)
        assert plc_sim._read_int('i_MANIFOLD_ID') == int(sample_payload.manifold_id)

def test_custom_solvent_handling(plc_sim, sample_payload, sample_custom_solvent):
    """Test handling of custom solvent parameters."""
    with plc_sim:
        # Modify payload to use custom solvent
        payload = sample_payload
        payload.org_solvent_id = OrgSolventID.CUSTOM
        payload.custom_solvent = sample_custom_solvent
        
        plc_sim.write_payload_to_plc(payload)
        
        # Verify custom solvent parameters
        assert plc_sim._read_string('s_CUSTOM_ORG_SOLVENT') == sample_custom_solvent.name
        assert abs(plc_sim._read_real('r_VISCOSITY') - sample_custom_solvent.viscosity) < 1e-6
        assert abs(plc_sim._read_real('r_SENSITIVITY') - sample_custom_solvent.sensitivity) < 1e-6
        assert abs(plc_sim._read_real('r_MOLAR_VOLUME') - sample_custom_solvent.molar_volume) < 1e-6

def test_command_exclusivity(plc_sim):
    """Test command bit exclusivity rules."""
    with plc_sim:
        # Set START in RUN mode
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        assert plc_sim._read_bool('COMMANDS_RUN.b_START')
        
        # Set START in CLEAN mode - should clear RUN mode's START
        plc_sim.pulse_cmd(MachineMode.CLEAN, ModeCmds.START, True)
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert plc_sim._read_bool('COMMANDS_CLEAN.b_START')

def test_stop_command_clearing(plc_sim):
    """Test that STOP command clears other bits in the same mode."""
    with plc_sim:
        # Set multiple bits in RUN mode
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.START, True)
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.PAUSE_PLAY, True)
        
        # Issue STOP command
        plc_sim.pulse_cmd(MachineMode.RUN, ModeCmds.STOP, True)
        
        # Verify all other bits are cleared
        assert not plc_sim._read_bool('COMMANDS_RUN.b_START')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_PAUSE_PLAY')
        assert not plc_sim._read_bool('COMMANDS_RUN.b_CONFIRM')
