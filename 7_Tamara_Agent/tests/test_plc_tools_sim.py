"""
Tests for PLC communication tools in simulation mode

Author: 
"""

import os
import pytest
from ..agent_poc_V0 import PLCInterface, InputPayload, ChipID, Manifold, Mode

@pytest.fixture
def plc_sim():
    # Set environment to simulation mode
    os.environ['PLC_IP'] = 'SIM'
    return PLCInterface()

def test_write_and_read_sim(plc_sim):
    # Create test payload
    payload = InputPayload(
        tfr=6.0,
        frr_aq=3,
        frr_sol=1,
        target_volume=1.0,
        temperature=22.0,
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    # Write payload to simulator
    plc_sim.write_payload_to_plc(payload)
    
    # Initially validation bit should be False
    assert not plc_sim.read_validation_bit()
    
    # Set validation bit True and verify
    plc_sim.client.set_validation_bit(True)
    assert plc_sim.read_validation_bit()
    
    # Set validation bit False and verify
    plc_sim.client.set_validation_bit(False)
    assert not plc_sim.read_validation_bit()

def test_simulator_state_persistence(plc_sim):
    # Create test payload
    payload = InputPayload(
        tfr=6.0,
        frr_aq=3,
        frr_sol=1,
        target_volume=1.0,
        temperature=22.0,
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    # Write payload and verify it's stored
    plc_sim.write_payload_to_plc(payload)
    assert plc_sim.client.inputs == payload.__dict__
    
    # Write new payload and verify it updates
    new_payload = InputPayload(
        tfr=8.0,
        frr_aq=4,
        frr_sol=1,
        target_volume=2.0,
        temperature=25.0,
        chip_id=ChipID.BAFFLE,
        manifold=Manifold.LARGE,
        mode=Mode.CLEAN
    )
    
    plc_sim.write_payload_to_plc(new_payload)
    assert plc_sim.client.inputs == new_payload.__dict__

def test_validation_bit_toggle(plc_sim):
    # Test multiple toggles of validation bit
    states = [True, False, True, True, False]
    
    for state in states:
        plc_sim.client.set_validation_bit(state)
        assert plc_sim.read_validation_bit() == state
