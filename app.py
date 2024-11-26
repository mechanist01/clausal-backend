from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime
import logging
import fitz  # PyMuPDF
from dotenv import load_dotenv
from contract_analyzer import ContractAnalyzer
from dataclasses import asdict
from contract_chat import ContractChat
import asyncio
from asgiref.wsgi import WsgiToAsgi
from hypercorn.config import Config
from hypercorn.asyncio import serve
from quart import Quart, request, jsonify  # Updated to use Quart
from quart_cors import cors  # Updated to use Quart CORS
from risk_assessment import ContractRiskAssessor  # Import the risk assessor
import traceback  # Import traceback for detailed error logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

app = Quart(__name__)  # Initialize Quart app
app = cors(app)  # Enable CORS for the app

# Configuration
UPLOAD_FOLDER = 'uploads'
RESPONSE_FOLDER = 'responses'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}

# Ensure required folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESPONSE_FOLDER, exist_ok=True)

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    RESPONSE_FOLDER=RESPONSE_FOLDER,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16MB max file size
)

# Initialize the risk assessor
risk_assessor = ContractRiskAssessor()

def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from PDF file."""
    logging.info(f"Starting PDF text extraction from {file_path}")
    try:
        doc = fitz.open(file_path)
        logging.info(f"PDF has {len(doc)} pages")
        
        text = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            if page_text:
                text.append(page_text)
                logging.info(f"Extracted {len(page_text)} characters from page {page_num + 1}")
            else:
                logging.warning(f"No text extracted from page {page_num + 1}")
        
        doc.close()
        full_text = "\n".join(text)
        
        if not full_text:
            logging.error("No text was extracted from the PDF")
            raise ValueError("No text could be extracted from the PDF")
            
        logging.info(f"Successfully extracted total of {len(full_text)} characters")
        return full_text
            
    except Exception as e:
        logging.error(f"Error extracting text from PDF: {str(e)}")
        raise

def save_analysis_response(original_filename: str, response_data: dict) -> str:
    """Save analysis response to JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response_filename = f"{original_filename}_{timestamp}.json"
    response_path = os.path.join(app.config['RESPONSE_FOLDER'], response_filename)
    
    response_with_metadata = {
        'timestamp': datetime.now().isoformat(),
        'original_filename': original_filename,
        'analysis': response_data
    }
    
    with open(response_path, 'w', encoding='utf-8') as f:
        json.dump(response_with_metadata, f, ensure_ascii=False, indent=2)
    
    return response_filename

@app.route('/analyze', methods=['POST'])
def analyze_contract():
    """Endpoint for analyzing contract documents."""
    logging.info("Starting contract analysis request")
    file_path = None
    
    try:
        # Validate file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file or not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        # Process the file
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(file_path)
            
            # Extract text content
            file_content = extract_text_from_pdf(file_path)
            
            # Initialize analyzer
            analyzer = ContractAnalyzer()
            
            # Analyze contract
            analysis_result = analyzer.analyze_contract(file_content)
            
            # Convert dataclass to dict for JSON serialization
            analysis_dict = {
                'analysis': asdict(analysis_result),
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'filename': filename,
                    'filesize': os.path.getsize(file_path)
                }
            }
            
            # Save response
            saved_filename = save_analysis_response(filename, analysis_dict)
            
            return jsonify({
                'status': 'success',
                'analysis': analysis_dict['analysis'],
                'metadata': analysis_dict['metadata'],
                'saved_response_file': saved_filename
            })
            
        except Exception as e:
            logging.error(f"Error processing contract: {str(e)}")
            raise
            
    except Exception as e:
        error_message = str(e)
        logging.error(f"Error in contract analysis: {error_message}")
        return jsonify({
            'error': 'Server error',
            'details': error_message
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file size limit exceeded error."""
    return jsonify({
        'error': 'File too large',
        'details': 'The file size exceeds the maximum allowed limit of 16MB'
    }), 413

chat_handler = ContractChat()

@app.route('/contractIQ', methods=['POST'])
async def chat_with_contract():
    try:
        data = await request.get_json()
        logging.info(f"Received chat request: {data}")
        
        if not data or 'message' not in data or 'contractId' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        contract_path = os.path.join(app.config['UPLOAD_FOLDER'], data['contractId'])
        logging.info(f"Looking for contract at: {contract_path}")

        if not os.path.exists(contract_path):
            logging.error(f"Contract not found at: {contract_path}")
            return jsonify({'error': 'Contract not found'}), 404

        # Get chat history
        chat_history = chat_handler.chat_histories.get(data['contractId'], [])

        try:
            # Get contract text if this is the first message
            contract_text = None
            if not chat_history:
                logging.info("First message - loading contract text")
                contract_text = extract_text_from_pdf(contract_path)
                logging.info(f"Extracted {len(contract_text)} characters from contract")
            else:
                # Use empty string for contract text since it's already in context
                contract_text = ""

            logging.info("Getting response from chat handler")
            response = await chat_handler.get_response(
                message=data['message'],
                contract_id=data['contractId'],
                contract_text=contract_text,
                chat_history=chat_history
            )
            logging.info("Got response from chat handler")
            
            response_dict = asdict(response)
            logging.info("Converted response to dict")
            
            return jsonify(response_dict)

        except Exception as e:
            logging.error(f"Error in chat processing: {str(e)}")
            return jsonify({
                'error': 'Chat processing error',
                'details': str(e)
            }), 500

    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({
            'error': 'Server error',
            'details': str(e)
        }), 500

@app.route('/riskassess', methods=['POST'])
async def assess_contract_risks():
    """Endpoint for assessing contract risks."""
    try:
        data = await request.get_json()
        logging.info(f"Received risk assessment request with data: {data}")
        
        contract_id = data.get('contract_id')
        if not contract_id:
            logging.error("Missing contract_id in request")
            return jsonify({'error': 'Missing contract_id'}), 400

        logging.info(f"Looking for contract analysis with ID: {contract_id}")

        # First try to get cached assessment
        cached_assessment = await risk_assessor.get_cached_assessment(contract_id)
        if cached_assessment:
            logging.info("Found cached assessment")
            return jsonify(asdict(cached_assessment))

        # Log the contents of the response folder
        response_files = os.listdir(app.config['RESPONSE_FOLDER'])
        logging.info(f"Available response files: {response_files}")

        # Find the most recent analysis file for this contract
        matching_files = [f for f in response_files if f.startswith(contract_id)]
        if not matching_files:
            logging.error(f"No analysis files found for contract_id: {contract_id}")
            return jsonify({
                'error': 'Contract analysis not found',
                'details': f'No analysis file found for ID {contract_id}'
            }), 404

        # Sort by timestamp and get the most recent
        response_file = sorted(matching_files)[-1]
        logging.info(f"Using most recent analysis file: {response_file}")

        # Load the contract analysis
        analysis_path = os.path.join(app.config['RESPONSE_FOLDER'], response_file)
        logging.info(f"Loading analysis from: {analysis_path}")
        
        try:
            with open(analysis_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
                logging.info(f"File content (first 200 chars): {file_content[:200]}")
                contract_analysis = json.loads(file_content)
                logging.info("Successfully loaded and parsed contract analysis")
                
                # Extract the actual analysis data from the nested structure
                contract_data = contract_analysis.get('analysis', {})
                if isinstance(contract_data, dict) and 'analysis' in contract_data:
                    contract_data = contract_data['analysis']
                
                logging.info(f"Extracted contract data structure: {list(contract_data.keys())}")
                
        except json.JSONDecodeError as e:
            logging.error(f"JSON parsing error: {str(e)}")
            logging.error(f"Error location: line {e.lineno}, column {e.colno}")
            with open(analysis_path, 'r', encoding='utf-8') as f:
                problematic_line = f.readlines()[e.lineno - 1]
                logging.error(f"Problematic line: {problematic_line}")
            return jsonify({
                'error': 'Invalid JSON in analysis file',
                'details': f'JSON parsing error at line {e.lineno}, column {e.colno}'
            }), 500
        except Exception as e:
            logging.error(f"Error loading contract analysis: {str(e)}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            return jsonify({
                'error': 'Error loading contract analysis',
                'details': str(e)
            }), 500

        # Perform risk assessment
        try:
            assessment_result = await risk_assessor.assess_risks(contract_data)
            logging.info("Successfully completed risk assessment")
            return jsonify(asdict(assessment_result))
        except Exception as e:
            logging.error(f"Error during risk assessment: {str(e)}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            return jsonify({
                'error': 'Risk assessment failed',
                'details': str(e)
            }), 500

    except Exception as e:
        logging.error(f"Error in risk assessment endpoint: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'error': 'Server error',
            'details': str(e)
        }), 500

if __name__ == '__main__':
    logging.info("Starting Quart server...")
    app.run(debug=True, host='0.0.0.0', port=5000)  # Run the Quart app