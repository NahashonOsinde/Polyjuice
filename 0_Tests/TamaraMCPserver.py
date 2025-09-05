from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import math
from mcp.server.fastmcp import FastMCP
import snap7
from snap7.util import set_real, get_real, set_bool, get_bool

# Initialize FastMCP server
mcp = FastMCP("tamara")

# System constants
P_MIN_BAR = 0.2      # Minimum pressure (bar)
T_PRIME_S = 0.5      # Prime delay for amorcage + priming (s)
T_MIN_S = 3          # Minimum runtime for stable pressure (s)
MU_REF = 1005.0      # Reference viscosity - water at 20°C (μPa·s)
MANIFOLD_VOL = {     # Maximum volumes for manifolds (mL)
    "SMALL": 1.7,
    "LARGE": 23.0
}

# Solvent properties at 20°C
SOLVENT_PROPERTIES = {
    'ethanol': {
        'viscosity': 1184.0,  # Base viscosity at 20°C (μPa·s)
        'sensitivity': 22.0,  # Temperature sensitivity (μPa·s/°C)
        'molar_volume': 22.0  # Molar volume (mL/mol)
    },
    'ipa': {
        'viscosity': 2381.0,
        'sensitivity': 68.0,
        'molar_volume': 103.0
    },
    'acetone': {
        'viscosity': 324.0,
        'sensitivity': 3.0,
        'molar_volume': 74.0
    },
    'methanol': {
        'viscosity': 594.0,
        'sensitivity': 7.0,
        'molar_volume': 40.0
    }
}

# Chip-specific geometry resistances
CHIP_RESISTANCES = {
    "BAFFLE": {
        "1": 14.43,     # Linear resistance (mbar·s/μL)
        "2": 59.80,
        "3": 3.08,
        "1a": 0.04118,  # Quadratic resistance (mbar·s²/μL²)
        "2a": 0.28768,
        "3a": 0.03947
    },
    "HERRINGBONE": {
        "1": 12.06,
        "2": 61.29,
        "3": 5.09,
        "1a": 0.07357,
        "2a": 0.25822,
        "3a": 0.0
    }
}

# === PLC Connection Settings ===
PLC_IP = "192.168.0.1"     # <-- Replace with actual IP
DB_NUMBER = 9               # DB9 = DB_Experiments_
BYTE_INDEX = 2              # Byte offset for sequence start
# BIT_INDEX = 0              # Bit offset for

# ---------------------------------------------------------------------------
# Sequencing layer constants (mirrors mcp_params.py)
# ---------------------------------------------------------------------------
MODE_RUN = "RUN"
MODE_CLEAN = "CLEAN"
MODE_PRESSURE_TEST = "PRESSURE_TEST"

CLEAN_CONSTANT = "constant"
CLEAN_ALTERNATE = "alternate"

@dataclass
class RunParameters:
    # User inputs
    tfr: float                  # Total Flow Rate (mL/min)
    frr: int                    # Flow Rate Ratio (aqueous:solvent)
    tar_vol: float             # Target Volume (mL)
    temp: float                # Temperature (°C)
    chip_id: str               # Chip type (BAFFLE/HERRINGBONE)
    manifold: str              # Manifold size (SMALL/LARGE)
    viscosity_org: float       # Base viscosity of organic at 20°C (μPa·s)
    viscosity_sens: float      # Viscosity temperature sensitivity (μPa·s/°C)
    molar_vol: float          # Molar volume of organic (mL/mol)
    lab_pressure: float        # Maximum input pressure (bar)

    # Derived parameters
    mu1: float = 0.0          # Viscosity of aqueous phase (μPa·s)
    mu2: float = 0.0          # Viscosity of organic phase (μPa·s)
    n: float = 0.0            # Ratio of organic to aqueous phase
    mu3: float = 0.0          # Viscosity of mixture (μPa·s)
    tfrmin: float = 0.0       # Minimum total flow rate (mL/min)
    tfrmax: float = 0.0       # Maximum total flow rate (mL/min)
    
    # Adjusted resistances
    resis: Dict[str,float] = field(default_factory=dict)
    
    # Effective linear & quad resistances
    r1: float = 0.0
    ra1: float = 0.0
    r2: float = 0.0
    ra2: float = 0.0
    
    # Split volumes & runtime
    v1: float = 0.0           # Organic phase volume
    v2: float = 0.0           # Aqueous phase volume
    run_time: float = 0.0     # Runtime (Amorcage + priming + run) (s)
    
    # Flows
    flow1: float = 0.0
    flow2: float = 0.0
    
    # Pressures (bar)
    press1: float = 0.0
    press2: float = 0.0

def compute_derived_parameters(rp: RunParameters) -> None:
    """Compute all derived parameters for a RunParameters instance."""
    # 1. Dynamic Viscosity Calculations
    rp.mu1 = 1005.0 - 23.0 * (rp.temp - 20.0)  # Aqueous phase viscosity (water)
    rp.mu2 = rp.viscosity_org - rp.viscosity_sens * (rp.temp - 20.0)
    rp.n = rp.frr * (rp.molar_vol / 18.0)  # FRR is already the ratio
    rp.mu3 = (rp.mu1 * rp.n + rp.mu2) / (1 + rp.n)

    # 2. Viscosity-Adjusted Resistances
    base_resis = CHIP_RESISTANCES[rp.chip_id]
    for seg, base in base_resis.items():
        if seg in ("1", "1a"):
            mu_i = rp.mu1
        elif seg in ("2", "2a"):
            mu_i = rp.mu2
        else:
            mu_i = rp.mu3
        rp.resis[seg] = base * (mu_i / MU_REF)

    # 3. Effective Resistance per Line
    fr_rate = rp.frr  # FRR is already the ratio
    rp.r1 = rp.resis["1"] * (fr_rate / (1 + fr_rate)) + rp.resis["3"]
    rp.ra1 = rp.resis["1a"] * ((fr_rate / (1 + fr_rate)) ** 2) + rp.resis["3a"]
    rp.r2 = rp.resis["2"] * (1 / (1 + fr_rate)) + rp.resis["3"]
    rp.ra2 = rp.resis["2a"] * ((1 / (1 + fr_rate)) ** 2) + rp.resis["3a"]

    # 4. Compute TFRmin and TFRmax (in mL/min)
    p_min_mbar = P_MIN_BAR * 1000
    p_max_mbar = 0.9 * rp.lab_pressure * 1000

    # TFRmin calculations
    if rp.ra1 != 0:
        tfrmin1 = (-rp.r1 + math.sqrt(rp.r1**2 + 4 * p_min_mbar * rp.ra1)) / (2 * rp.ra1)
    else:
        tfrmin1 = p_min_mbar / rp.r1
    
    if rp.ra2 != 0:
        tfrmin2 = (-rp.r2 + math.sqrt(rp.r2**2 + 4 * p_min_mbar * rp.ra2)) / (2 * rp.ra2)
    else:
        tfrmin2 = p_min_mbar / rp.r2
    
    tfrmin_ul_per_s = max(tfrmin1, tfrmin2)
    rp.tfrmin = tfrmin_ul_per_s / 1000 * 60

    # TFRmax calculations
    if rp.ra1 != 0:
        tfrmax1 = (-rp.r1 + math.sqrt(rp.r1**2 + 4 * p_max_mbar * rp.ra1)) / (2 * rp.ra1)
    else:
        tfrmax1 = p_max_mbar / rp.r1
    
    if rp.ra2 != 0:
        tfrmax2 = (-rp.r2 + math.sqrt(rp.r2**2 + 4 * p_max_mbar * rp.ra2)) / (2 * rp.ra2)
    else:
        tfrmax2 = p_max_mbar / rp.r2
    
    tfrmax_ul_per_s = min(tfrmax1, tfrmax2)
    tfrmax_time = rp.tar_vol / T_MIN_S  # mL/s
    tfrmax_time_ml_min = tfrmax_time * 60  # mL/min
    rp.tfrmax = min(tfrmax_ul_per_s / 1000 * 60, tfrmax_time_ml_min)
    
    if rp.tfrmax <= rp.tfrmin:
        rp.tfrmax = rp.tfrmin + 1

    # 5. Volumes and Runtime
    rp.v1 = rp.tar_vol / (1 + fr_rate)  # organic phase
    rp.v2 = rp.v1 * fr_rate             # aqueous phase
    tfr_ml_per_s = rp.tfr / 60
    rp.run_time = rp.tar_vol / tfr_ml_per_s + T_PRIME_S

    # 6. Flows and Pressures
    Q = rp.tfr * 1000 / 60  # Convert to μL/s
    rp.flow1 = rp.tfr * (fr_rate / (1 + fr_rate))
    rp.flow2 = rp.tfr * (1 / (1 + fr_rate))
    rp.press1 = (Q * rp.r1 + Q**2 * rp.ra1 + 10) / 1000  # bar
    rp.press2 = (Q * rp.r2 + Q**2 * rp.ra2 + 10) / 1000  # bar

def validate_parameters(rp: RunParameters) -> tuple[List[str], List[str], List[str]]:
    """Validate parameters and return errors, warnings, and recommendations."""
    errs, warns, recs = [], [], []
    max_pressure = 0.9 * rp.lab_pressure
    
    # Pressure limits
    for name, p in (("press1", rp.press1), ("press2", rp.press2)):
        if p < P_MIN_BAR or p > max_pressure:
            errs.append(f"{name}={p:.2f} bar out of [{P_MIN_BAR},{max_pressure:.2f}] bar")
            recs.append("Consider adjusting TFR or FRR to bring pressures within limits")
    
    # Manifold capacity
    limit = MANIFOLD_VOL[rp.manifold]
    total_vol = rp.v1 + rp.v2
    if total_vol > limit:
        if rp.manifold == "SMALL" and total_vol <= MANIFOLD_VOL["LARGE"]:
            warns.append(f"Total volume {total_vol:.2f} mL exceeds SMALL manifold capacity")
            recs.append("Switch to LARGE manifold")
        else:
            errs.append(f"Total volume {total_vol:.2f} mL exceeds {rp.manifold} manifold capacity")
            recs.append("Reduce target volume or adjust TFR/FRR")
    
    # FRR limit
    if not (1 <= rp.frr <= 10):
        errs.append(f"FRR={rp.frr} out of [1,10] allowed range")
        recs.append("Adjust FRR to be between 1 and 10")
    
    # TFR dynamic limits
    if not (rp.tfrmin <= rp.tfr <= rp.tfrmax):
        errs.append(f"TFR={rp.tfr:.2f} mL/min out of [{rp.tfrmin:.2f},{rp.tfrmax:.2f}] mL/min")
        recs.append("Adjust TFR to be within computed limits")
    
    return errs, warns, list(set(recs))  # Remove duplicate recommendations

def build_sequence(rp: RunParameters, mode: str = MODE_RUN, clean_type: Optional[str] = None) -> List[float]:
    """Return a 10-element PLC sequence array based on the requested mode.

    Parameters
    ----------
    rp : RunParameters
        Object populated with ``press1``, ``press2`` and ``run_time``.
    mode : str, default "RUN"
        One of ``MODE_RUN``, ``MODE_CLEAN`` or ``MODE_PRESSURE_TEST``.
    clean_type : Optional[str]
        Required when ``mode == MODE_CLEAN``. Either ``CLEAN_CONSTANT`` or
        ``CLEAN_ALTERNATE``.
    """

    # ------------------------- RUN (mode 0) ------------------------------
    if mode == MODE_RUN:
        mode_code = 0.0
        # 30 % – 60 % – 100 % pressure ramp
        p_factors = (0.3, 0.6, 1.0)
        durations = (rp.run_time * 0.10, rp.run_time * 0.10, rp.run_time * 0.80)

        p1_vals = [rp.press1 * f for f in p_factors]
        p2_vals = [rp.press2 * f for f in p_factors]

    # ---------------------- CLEAN (modes 1 & 2) --------------------------
    elif mode == MODE_CLEAN:
        if clean_type == CLEAN_CONSTANT:
            mode_code = 1.0
            p1_vals = [rp.press1 * 0.5, 0.0, 0.0]
            p2_vals = [rp.press2 * 0.5, 0.0, 0.0]
            durations = (10.0, 0.0, 0.0)
        elif clean_type == CLEAN_ALTERNATE:
            mode_code = 2.0
            p1_vals = [rp.press1, 0.0, rp.press1]
            p2_vals = [rp.press2, 0.0, rp.press2]
            durations = (5.0, 5.0, 5.0)
        else:
            raise ValueError("When mode is CLEAN, clean_type must be 'constant' or 'alternate'.")

    # ------------------- PRESSURE TEST (mode 3) --------------------------
    elif mode == MODE_PRESSURE_TEST:
        mode_code = 3.0
        p1_vals = [rp.press1, 0.0, 0.0]
        p2_vals = [rp.press2, 0.0, 0.0]
        durations = (5.0, 0.0, 0.0)

    else:
        raise ValueError(f"Unknown mode '{mode}'.")

    sequence = [mode_code, *p1_vals, *p2_vals, *durations]
    if len(sequence) != 10:
        raise AssertionError("Generated PLC sequence must have exactly 10 elements.")
    return sequence

@mcp.tool()
async def compute_parameters(
    tfr: float,
    frr: int,
    tar_vol: float,
    temp: float,
    chip_id: str,
    manifold: str,
    solvent_type: str,
    lab_pressure: float,
    viscosity: Optional[float] = None,
    sensitivity: Optional[float] = None,
    molar_volume: Optional[float] = None,
    mode: str = MODE_RUN,
    clean_type: Optional[str] = None
) -> str:
    """Compute and validate parameters for TAMARA operation.
    
    Args:
        tfr: Total Flow Rate (mL/min)
        frr: Flow Rate Ratio (aqueous:solvent)
        tar_vol: Target Volume (mL)
        temp: Temperature (°C)
        chip_id: Chip type (BAFFLE/HERRINGBONE)
        manifold: Manifold size (SMALL/LARGE)
        solvent_type: Type of organic solvent (ethanol/ipa/acetone/methanol or custom)
        lab_pressure: Maximum input pressure (bar)
        viscosity: (optional) Custom viscosity at 20°C (μPa·s)
        sensitivity: (optional) Custom temperature sensitivity (μPa·s/°C)
        molar_volume: (optional) Custom molar volume (mL/mol)
        mode: Operation mode (RUN/CLEAN/PRESSURE_TEST)
        clean_type: (optional) Clean type (constant/alternate)
    """
    try:
        # ------------------------------------------------------------------
        # 1. Determine whether the solvent is standard or custom.
        #    We normalise the solvent key so that variants such as
        #    "ethyl acetate", "Ethyl-Acetate", "ETHYLACETATE" etc. are
        #    treated equivalently.  Hyphens and whitespaces are stripped and
        #    the key is converted to lowercase for matching.
        # ------------------------------------------------------------------
        raw_key = solvent_type.strip().lower()
        norm_key = raw_key.replace(" ", "").replace("-", "")

        # Build a mapping of normalised -> canonical keys for the standard
        # solvent dictionary once.  This lets us check membership using the
        # normalised key while still retrieving the canonical entry.
        std_norm_map = {k.replace(" ", "").replace("-", ""): k for k in SOLVENT_PROPERTIES}

        if norm_key in std_norm_map:
            canonical_key = std_norm_map[norm_key]
            solvent = SOLVENT_PROPERTIES[canonical_key]
            # Debug print for standard solvent
            print(f"DEBUG: Using standard solvent '{canonical_key}' with values: {solvent}")
        else:
            # If any property is missing, try to look up online
            missing = []
            if viscosity is None:
                missing.append("viscosity")
            if sensitivity is None:
                missing.append("sensitivity")
            if molar_volume is None:
                missing.append("molar_volume")
            if missing:
                found = {}
                if viscosity is None:
                    found["viscosity"] = f"[LOOKUP: viscosity of {solvent_type} at 20°C in μPa·s]"
                if sensitivity is None:
                    found["sensitivity"] = f"[LOOKUP: viscosity temperature sensitivity of {solvent_type} in μPa·s/°C]"
                if molar_volume is None:
                    found["molar_volume"] = f"[LOOKUP: molar volume of {solvent_type} in mL/mol]"
                msg = (
                    f"Custom solvent '{solvent_type}' detected.\n"
                    f"The following properties are required but missing: {', '.join(missing)}.\n"
                    f"Attempted to look up values online (please validate or override):\n"
                )
                for k, v in found.items():
                    msg += f"  {k}: {v}\n"
                msg += (
                    "\nPlease provide these values explicitly in your next request, or confirm the above values if correct."
                )
                return msg
            # If all provided, use them
            debug_msg = (
                f"DEBUG: Using custom solvent '{solvent_type}' with values:\n"
                f"  viscosity: {viscosity} (type: {type(viscosity)})\n"
                f"  sensitivity: {sensitivity} (type: {type(sensitivity)})\n"
                f"  molar_volume: {molar_volume} (type: {type(molar_volume)})\n"
            )
            print(debug_msg)
            if not all(isinstance(x, (float, int)) for x in [viscosity, sensitivity, molar_volume]):
                return (f"ERROR: Custom solvent values must be numbers. Got: viscosity={viscosity}, sensitivity={sensitivity}, molar_volume={molar_volume}")
            solvent = {
                'viscosity': float(viscosity),
                'sensitivity': float(sensitivity),
                'molar_volume': float(molar_volume)
            }

            # Persist the custom solvent in memory so subsequent calls can
            # reuse it without re-entering the properties.
            SOLVENT_PROPERTIES[raw_key] = solvent

            # Final debug print of solvent dict
            print(f"DEBUG: Registered custom solvent '{raw_key}' with properties: {solvent}")

        # Only use the local 'solvent' dict from here on
        viscosity_value = solvent['viscosity']
        sensitivity_value = solvent['sensitivity']
        molar_volume_value = solvent['molar_volume']
        # Create RunParameters instance
        rp = RunParameters(
            tfr=tfr,
            frr=frr,
            tar_vol=tar_vol,
            temp=temp,
            chip_id=chip_id.upper(),
            manifold=manifold.upper(),
            viscosity_org=viscosity_value,
            viscosity_sens=sensitivity_value,
            molar_vol=molar_volume_value,
            lab_pressure=lab_pressure
        )
        
        # Compute derived parameters
        compute_derived_parameters(rp)
        
        # Validate parameters
        errs, warns, recs = validate_parameters(rp)
        
        # Build sequence according to requested mode
        try:
            sequence = build_sequence(rp, mode, clean_type)
        except ValueError as seq_err:
            return f"Error: {seq_err}"
        
        # Format response
        response = []
        
        if errs:
            response.append("ERRORS:")
            response.extend(f"- {err}" for err in errs)
            response.append("")
        
        if warns:
            response.append("WARNINGS:")
            response.extend(f"- {warn}" for warn in warns)
            response.append("")
        
        if recs:
            response.append("RECOMMENDATIONS:")
            response.extend(f"- {rec}" for rec in recs)
            response.append("")
        
        if not errs:  # Only show parameters if no errors
            response.extend([
                "COMPUTED PARAMETERS:",
                f"- Pressure 1: {rp.press1:.3f} bar",
                f"- Pressure 2: {rp.press2:.3f} bar",
                f"- Organic phase volume: {rp.v1:.2f} mL",
                f"- Aqueous phase volume: {rp.v2:.2f} mL",
                f"- Total runtime: {rp.run_time:.1f} s",
                f"- Flow rate 1: {rp.flow1:.2f} mL/min",
                f"- Flow rate 2: {rp.flow2:.2f} mL/min",
                "",
                "SEQUENCE ARRAY:",
                f"{[f'{x:.2f}' for x in sequence]}"
            ])
        
        return "\n".join(response)
        
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def send_to_tamara(sequence: List[float], mode: str = MODE_RUN) -> str:
    """Send sequence to TAMARA via PLC and read back for verification.
    
    Args:
        sequence: List of 10 float values for the sequence
        mode: Operation mode (RUN/CLEAN/PRESSURE_TEST)
    """
    try:
        # Connect to PLC
        client = snap7.client.Client()
        client.connect(PLC_IP, 0, 1)  # Rack=0, Slot=1 for S7-1200
        if not client.get_connected():
            return "Error: Could not connect to PLC."

        # Prepare data: pack 10 floats (REAL, 4 bytes each) into a bytearray
        data = bytearray(40)  # 10 * 4 bytes
        for i, value in enumerate(sequence):
            set_real(data, i * 4, float(value))

        # Write to PLC DB
        client.db_write(DB_NUMBER, BYTE_INDEX, data)

        # Write to PLC DB (b_StartSeq)
        StartSeq_data = bytearray(1)
        set_bool(StartSeq_data, 0, 1, True)
        client.db_write(DB_NUMBER, 166, StartSeq_data) #Having hard-coded this value is not safe. For now, it's the only way to start the sequence.

        # Read back the same 40 bytes
        # Optionally unpack and check values
        readback = client.db_read(DB_NUMBER, BYTE_INDEX, 40)
        readback_values = [get_real(readback, i * 4) for i in range(10)]

        client.disconnect()
        return (
            f"Successfully sent {mode} sequence to TAMARA PLC: {sequence}\n"
            f"Read-back values from PLC: {[f'{v:.2f}' for v in readback_values]}"
        )
    except Exception as e:
        return f"Error sending sequence to TAMARA: {str(e)}"

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
