# TAMARA Agent POC

A proof-of-concept implementation of an agentic interface for TAMARA that combines RAG capabilities with PLC communication.

## Features

- Chat-based interface for TAMARA operation
- Local RAG (Retrieval Augmented Generation) for answering questions from knowledge base
- PLC communication for formulation run validation
- Support for Run, Clean, and Pressure Test modes
- Static input validation
- Simulation mode for testing without PLC connection

## Setup

1. Create and activate a Python virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables in `.env`:
```
PLC_IP=192.168.1.100  # Use 'SIM' for simulation mode
PLC_RACK=0
PLC_SLOT=1
OPENAI_API_KEY=your_api_key_here
```

4. Build the RAG index:
```bash
python rag_build.py
```

## Usage

Run the agent:
```bash
python agent_poc.py
```

For dry-run mode (no PLC communication):
```bash
python agent_poc.py --dry-run
```

## Testing

Run tests:
```bash
pytest tests/
```

## Project Structure

- `agent_poc.py` - Main agent implementation
- `rag_build.py` - RAG index builder
- `tests/` - Test suite
  - `test_static_validation.py` - Input validation tests
  - `test_plc_tools_sim.py` - PLC simulation tests
  - `test_rag_local.py` - RAG functionality tests
- `requirements.txt` - Project dependencies

## PLC Communication

The agent communicates with the PLC using the following DB layout:

- DB100.DBD0: TFR (REAL)
- DB100.DBW4: FRR_AQ (INT)
- DB100.DBW6: FRR_SOL (INT)
- DB100.DBD8: Target Volume (REAL)
- DB100.DBD12: Temperature (REAL)
- DB100.DBW16: Chip ID (INT)
- DB100.DBW18: Manifold (INT)
- DB100.DBW20: Mode (INT)
- DB100.DBX22.0: Validation Bit

## Static Validation Rules

- TFR: 0.8-15.0 mL/min
- FRR: Positive integers only
- Temperature: 5-60°C
- Target Volume: Positive value
- Chip ID: HERRINGBONE or BAFFLE
- Manifold: SMALL or LARGE
- Mode: RUN, CLEAN, or PRESSURE_TEST

## RAG Implementation

- Uses ChromaDB as vector store
- Chunk size: 1,200 characters
- Chunk overlap: 200 characters
- Top-k retrieval: 4 documents
- Embeddings: OpenAI
