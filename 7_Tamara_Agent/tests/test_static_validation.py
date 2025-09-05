"""
Unit tests for static validation of TAMARA inputs

Author: 
"""

import pytest
from ..agent_poc import InputPayload, ChipID, Manifold, Mode, static_validate

def test_valid_inputs():
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
    
    valid, messages = static_validate(payload)
    assert valid
    assert not messages

def test_tfr_bounds():
    # Test lower bound
    payload = InputPayload(
        tfr=0.7,  # Below min 0.8
        frr_aq=3,
        frr_sol=1,
        target_volume=1.0,
        temperature=22.0,
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    valid, messages = static_validate(payload)
    assert not valid
    assert any("TFR must be between" in msg for msg in messages)

    # Test upper bound
    payload.tfr = 15.1  # Above max 15.0
    valid, messages = static_validate(payload)
    assert not valid
    assert any("TFR must be between" in msg for msg in messages)

def test_frr_validation():
    # Test negative FRR
    payload = InputPayload(
        tfr=6.0,
        frr_aq=-1,
        frr_sol=1,
        target_volume=1.0,
        temperature=22.0,
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    valid, messages = static_validate(payload)
    assert not valid
    assert any("FRR values must be positive" in msg for msg in messages)

    # Test zero FRR
    payload.frr_aq = 0
    valid, messages = static_validate(payload)
    assert not valid
    assert any("FRR values must be positive" in msg for msg in messages)

def test_temperature_range():
    # Test low temperature
    payload = InputPayload(
        tfr=6.0,
        frr_aq=3,
        frr_sol=1,
        target_volume=1.0,
        temperature=4.0,  # Below min 5.0
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    valid, messages = static_validate(payload)
    assert not valid
    assert any("Temperature must be between" in msg for msg in messages)

    # Test high temperature
    payload.temperature = 61.0  # Above max 60.0
    valid, messages = static_validate(payload)
    assert not valid
    assert any("Temperature must be between" in msg for msg in messages)

def test_target_volume():
    # Test negative volume
    payload = InputPayload(
        tfr=6.0,
        frr_aq=3,
        frr_sol=1,
        target_volume=-1.0,
        temperature=22.0,
        chip_id=ChipID.HERRINGBONE,
        manifold=Manifold.SMALL,
        mode=Mode.RUN
    )
    
    valid, messages = static_validate(payload)
    assert not valid
    assert any("Target volume must be positive" in msg for msg in messages)

    # Test zero volume
    payload.target_volume = 0.0
    valid, messages = static_validate(payload)
    assert not valid
    assert any("Target volume must be positive" in msg for msg in messages)
