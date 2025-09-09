"""
Test configuration and fixtures for TAMARA Agent tests.
"""
import os
import pytest
from typing import Generator
from plc_tool import PLCInterface, InputPayload, CustomSolvent
from plc_tool import OperationMode, MachineMode, ChipID, ManifoldID, OrgSolventID

@pytest.fixture
def plc_sim() -> Generator[PLCInterface, None, None]:
    """Fixture that provides a PLCInterface in simulation mode."""
    os.environ['PLC_SIM'] = '1'  # Force simulation mode
    plc = PLCInterface(simulate=True)
    yield plc
    plc.disconnect()

@pytest.fixture
def sample_payload() -> InputPayload:
    """Fixture that provides a valid sample InputPayload."""
    return InputPayload(
        tfr=1.0,
        frr=5,
        target_volume=10.0,
        temperature=25.0,
        chip_id=ChipID.BAFFLE,
        manifold_id=ManifoldID.SMALL,
        lab_pressure=1000.0,
        org_solvent_id=OrgSolventID.ETHANOL,
        operation_mode=OperationMode.AGENTIC,
        machine_mode=MachineMode.RUN,
        custom_solvent=None
    )

@pytest.fixture
def sample_custom_solvent() -> CustomSolvent:
    """Fixture that provides a valid sample CustomSolvent."""
    return CustomSolvent(
        name="test_solvent",
        viscosity=1.23,
        sensitivity=0.045,
        molar_volume=12.34
    )
