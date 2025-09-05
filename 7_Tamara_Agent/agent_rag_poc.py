# TAMARA Agent POC - Main Entry Point
# This module implements a chat-based agent for TAMARA that combines RAG capabilities
# with PLC communication for formulation run validation.

# Author: Nahashon Osinde

# Add these imports at the top
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import time
import logging
import logging.handlers
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.prompt import Prompt
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
import snap7
from snap7.util import set_real, get_real, set_int, get_int, set_bool, get_bool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/agent_poc.log',
            maxBytes=1024*1024,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Verify required environment variables
required_env_vars = [
    "PLC_IP",
    "PLC_RACK",
    "PLC_SLOT",
    "DB_NUMBER",
    "PLC_DB_VALIDATION",
    "PLC_VALID_BIT_OFFSET"
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# PLC Configuration
PLC_CONFIG = {
    'ip': os.getenv('PLC_IP'),
    'rack': int(os.getenv('PLC_RACK')),
    'slot': int(os.getenv('PLC_SLOT')),
    'db_number': int(os.getenv('DB_NUMBER')),      # DB9 = DB_Experiments_
    'db_validation': int(os.getenv('PLC_DB_VALIDATION')),
}

# Parse validation bit offset (format: "byte.bit")
valid_bit_parts = os.getenv('PLC_VALID_BIT_OFFSET').split('.')
PLC_CONFIG['valid_bit_byte'] = int(valid_bit_parts[0])
PLC_CONFIG['valid_bit_bit'] = int(valid_bit_parts[1]) if len(valid_bit_parts) > 1 else 0

# PLC DB Constants for inputs (DB9 = DB_Experiments_)
DB_CONFIG = {
    'INPUTS': {
        'TFR': {'db_number': 9, 'start': 198, 'type': 'REAL'},        # Offset 198.0
        'FRR': {'db_number': 9, 'start': 202, 'type': 'INT'},         # Offset 202.0
        'TARGET_VOL': {'db_number': 9, 'start': 204, 'type': 'REAL'}, # Offset 204.0
        'TEMP': {'db_number': 9, 'start': 208, 'type': 'REAL'},       # Offset 208.0
        'CHIP_ID': {'db_number': 9, 'start': 212, 'type': 'INT'},     # Offset 212.0
        'MANIFOLD': {'db_number': 9, 'start': 214, 'type': 'INT'},    # Offset 214.0
        'MODE': {'db_number': 9, 'start': 216, 'type': 'INT'},        # Offset 216.0
        # 'CRUNCH_VALID': {'db_number': 9, 'start': 218, 'type': 'BOOL'} # Offset 218.0
    },
    'VALIDATION': {
        'CRUNCH_VALID': {'db_number': 9, 'start': 218, 'type': 'BOOL'}  # Offset 218.0 - Read-only validation bit
    }
}

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
    frr: int                  # Single FRR value (aqueous:solvent)
    target_volume: float
    temperature: float
    chip_id: ChipID
    manifold: Manifold
    mode: Mode

class PLCInterface:
    """Handles communication with the PLC"""
    def __init__(self):
        self.client = snap7.client.Client()
        self.connect()

    def connect(self) -> None:
        """Connect to the PLC"""
        try:
            self.client.connect(
                PLC_CONFIG['ip'],
                PLC_CONFIG['rack'],
                PLC_CONFIG['slot']
            )
            if not self.client.get_connected():
                raise ConnectionError("Failed to connect to PLC")
            logger.info("Successfully connected to PLC")
        except Exception as e:
            logger.error(f"Error connecting to PLC: {str(e)}")
            raise

    def disconnect(self) -> None:
        """Disconnect from the PLC"""
        if self.client.get_connected():
            self.client.disconnect()
            logger.info("Disconnected from PLC")

    def write_payload_to_plc(self, payload: InputPayload) -> None:
        """Write input payload to PLC DB"""
        try:
            # Write each value individually to avoid memory range issues
            db_number = DB_CONFIG['INPUTS']['TFR']['db_number']

            # Write TFR (REAL - 4 bytes)
            data = bytearray(4)
            set_real(data, 0, payload.tfr)
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['TFR']['start'], data)

            # Write FRR (INT - 2 bytes)
            data = bytearray(2)
            set_int(data, 0, payload.frr)
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['FRR']['start'], data)

            # Write Target Volume (REAL - 4 bytes)
            data = bytearray(4)
            set_real(data, 0, payload.target_volume)
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['TARGET_VOL']['start'], data)

            # Write Temperature (REAL - 4 bytes)
            data = bytearray(4)
            set_real(data, 0, payload.temperature)
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['TEMP']['start'], data)

            # Write ChipID (INT - 2 bytes)
            data = bytearray(2)
            set_int(data, 0, 0 if payload.chip_id == ChipID.HERRINGBONE else 1)  # 0=Herringbone, 1=Baffle
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['CHIP_ID']['start'], data)

            # Write Manifold (INT - 2 bytes)
            data = bytearray(2)
            set_int(data, 0, 1 if payload.manifold == Manifold.SMALL else 2)
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['MANIFOLD']['start'], data)

            # Write Mode (INT - 2 bytes)
            data = bytearray(2)
            mode_map = {Mode.RUN: 1, Mode.CLEAN: 2, Mode.PRESSURE_TEST: 3}
            set_int(data, 0, mode_map[payload.mode])
            self.client.db_write(db_number, DB_CONFIG['INPUTS']['MODE']['start'], data)

            logger.info("Successfully wrote payload to PLC")
            logger.info("Successfully wrote payload to PLC")

        except Exception as e:
            logger.error(f"Error writing to PLC: {str(e)}")
            raise

    def read_validation_bit(self) -> bool:
        """Read CRUNCH_VALID bit from PLC to check if limits are respected"""
        try:
            db_number = DB_CONFIG['VALIDATION']['CRUNCH_VALID']['db_number']
            byte_offset = DB_CONFIG['VALIDATION']['CRUNCH_VALID']['start']
            
            # Read the validation bit
            result = self.client.db_read(db_number, byte_offset, 1)
            return bool(result[0])
        except Exception as e:
            logger.error(f"Error reading validation bit: {str(e)}")
            raise

def collect_inputs(mode: Mode) -> InputPayload:
    """Collect and validate user inputs for TAMARA operation"""
    console = Console()
    
    try:
        tfr = float(Prompt.ask("Enter Total Flow Rate (mL/min)"))
        frr = int(Prompt.ask("Enter Flow Rate Ratio (integer)"))
        target_volume = float(Prompt.ask("Enter Target Volume (mL)"))
        temperature = float(Prompt.ask("Enter Temperature (°C)"))
        chip_id = ChipID(Prompt.ask("Enter Chip ID (HERRINGBONE/BAFFLE)").upper())
        manifold = Manifold(Prompt.ask("Enter Manifold (SMALL/LARGE)").upper())

        return InputPayload(
            tfr=tfr,
            frr=frr,
            target_volume=target_volume,
            temperature=temperature,
            chip_id=chip_id,
            manifold=manifold,
            mode=mode
        )
    except (ValueError, KeyError) as e:
        logger.error(f"Error collecting inputs: {str(e)}")
        raise typer.Exit(1)

def static_validate(payload: InputPayload) -> Tuple[bool, List[str]]:
    """Perform static validation of input parameters"""
    messages = []
    is_valid = True

    # Validate TFR range
    if not (0.8 <= payload.tfr <= 15.0):
        messages.append("TFR must be between 0.8 and 15.0 mL/min")
        is_valid = False

    # Validate FRR value
    if payload.frr <= 0:
        messages.append("FRR must be a positive integer")
        is_valid = False

    # Validate temperature range
    if not (5.0 <= payload.temperature <= 60.0):
        messages.append("Temperature must be between 5°C and 60°C")
        is_valid = False

    # Validate target volume
    if payload.target_volume <= 0:
        messages.append("Target volume must be positive")
        is_valid = False

    return is_valid, messages

def poll_plc_validation(plc: PLCInterface, timeout_s: float = 3.0) -> bool:
    """Poll PLC validation bit with timeout"""
    start_time = time.time()
    while time.time() - start_time < timeout_s:
        if plc.read_validation_bit():
            return True
        time.sleep(0.1)
    return False

class TamaraAgent:
    """Main agent class combining RAG and PLC control"""
    def __init__(self):
        self.console = Console()
        self.plc = PLCInterface()
        
        # Initialize RAG components
        self.vectorstore = Chroma(
            persist_directory="7_Tamara_Agent/db/chroma_db_with_metadata_Knowledge_base",
            embedding_function=OpenAIEmbeddings(
                model="text-embedding-3-small"
            )
        )
        
        # Create a retriever
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 15}
        )

        # Initialize LLM
        self.llm = ChatOpenAI(model="gpt-4")

        # Setup contextualization prompt
        contextualize_q_system_prompt = (
            "Given a chat history and the latest user question "
            "which might reference context in the chat history, "
            "formulate a standalone question which can be understood "
            "without the chat history. Do NOT answer the question, just "
            "reformulate it if needed and otherwise return it as is."
        )

        contextualize_q_prompt = ChatPromptTemplate.from_messages([
            ("system", contextualize_q_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}")
        ])

        # Create history-aware retriever
        self.history_aware_retriever = create_history_aware_retriever(
            self.llm, self.retriever, contextualize_q_prompt
        )

        # Setup QA prompt
        qa_system_prompt = """You are an AI assistant specializing in TAMARA, a microfluidic system. 
        Your role is to provide accurate, helpful information about TAMARA's operation, specifications, and best practices.
        
        When answering:
        1. Be precise and technical when discussing specifications
        2. Provide step-by-step guidance for operational questions
        3. Include relevant safety considerations
        4. If you're unsure or the information isn't in the context, say so
        5. Keep responses focused and relevant to TAMARA
        
        Use the following context to answer the question:
        {context}
        
        Base your answers solely on the provided context."""

        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", qa_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}")
        ])

        # Create QA chain
        question_answer_chain = create_stuff_documents_chain(
            self.llm, qa_prompt
        )

        # Create final RAG chain
        self.rag_chain = create_retrieval_chain(
            self.history_aware_retriever, 
            question_answer_chain
        )

        # Initialize chat history
        self.chat_history = []

    def process_run_request(self, mode: Mode) -> None:
        """Process a run request with input collection and validation"""
        try:
            # Collect inputs
            payload = collect_inputs(mode)
            logger.info(f"Collected inputs: {payload}")

            # Static validation
            valid, messages = static_validate(payload)
            if not valid:
                for msg in messages:
                    self.console.print(f"[red]Validation error: {msg}[/red]")
                return

            # Send to PLC
            self.plc.write_payload_to_plc(payload)
            logger.info("Inputs written to PLC")

            # Poll for validation
            if poll_plc_validation(self.plc):
                self.console.print("[green]Inputs accepted by PLC[/green]")
            else:
                self.console.print("[red]Inputs rejected by PLC - check PLC panel/logs[/red]")

        except Exception as e:
            logger.error(f"Error processing run request: {str(e)}")
            self.console.print(f"[red]Error: {str(e)}[/red]")

    def chat_loop(self) -> None:
        """Main chat loop"""
        self.console.print("[bold blue]TAMARA Agent POC[/bold blue]")
        self.console.print("Type 'exit' to quit")

        while True:
            try:
                user_input = Prompt.ask("\nYou:")
                
                if user_input.lower() == 'exit':
                    break

                # Check for run commands
                if any(cmd in user_input.lower() for cmd in ['run', 'formulate', 'clean', 'pressure test']):
                    mode = Mode.RUN
                    if 'clean' in user_input.lower():
                        mode = Mode.CLEAN
                    elif 'pressure test' in user_input.lower():
                        mode = Mode.PRESSURE_TEST
                    
                    self.process_run_request(mode)
                    continue

                # Process through RAG chain
                result = self.rag_chain.invoke({
                    "input": user_input,
                    "chat_history": self.chat_history
                })
                
                # Display response
                self.console.print(f"\nAI: {result['answer']}")
                
                # Update chat history
                self.chat_history.append(HumanMessage(content=user_input))
                self.chat_history.append(SystemMessage(content=result["answer"]))

            except Exception as e:
                logger.error(f"Error in chat loop: {str(e)}")
                self.console.print(f"[red]Error: {str(e)}[/red]")

def main():
    """Main entry point"""
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    agent = TamaraAgent()
    try:
        agent.chat_loop()
    finally:
        agent.plc.disconnect()

if __name__ == "__main__":
    typer.run(main)