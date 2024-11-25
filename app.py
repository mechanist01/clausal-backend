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

app = Flask(__name__)
CORS(app)

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
            
            # Try different text extraction methods
            page_text = page.get_text()
            
            if not page_text.strip():
                # Try with different flags if standard extraction fails
                page_text = page.get_text("text", flags=fitz.TEXT_PRESERVE_LIGATURES | 
                                               fitz.TEXT_PRESERVE_WHITESPACE | 
                                               fitz.TEXT_PRESERVE_SPANS)
            
            if not page_text.strip():
                # Try raw extraction as last resort
                page_text = page.get_text("rawdict")
                if page_text:
                    page_text = " ".join([b["text"] for b in page_text["blocks"] if "text" in b])
            
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
def chat_with_contract():
    try:
        data = request.json
        if not data or 'message' not in data or 'contractId' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        contract_path = os.path.join(app.config['UPLOAD_FOLDER'], data['contractId'])
        logging.info(f"Looking for contract at: {contract_path}")

        if not os.path.exists(contract_path):
            logging.error(f"Contract not found at: {contract_path}")
            return jsonify({'error': 'Contract not found'}), 404

        # Extract text from contract
        contract_text = extract_text_from_pdf(contract_path)

        # Get chat history
        chat_history = chat_handler.chat_histories.get(data['contractId'], [])

        response = chat_handler.get_response(
            message=data['message'],
            contract_id=data['contractId'],
            contract_text=contract_text,
            chat_history=chat_history
        )

        return jsonify(asdict(response))

    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({
            'error': 'Server error',
            'details': str(e)
        }), 500

if __name__ == '__main__':
    if not os.getenv('ANTHROPIC_API_KEY'):
        raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
        
    logging.info("Starting Flask server...")
    app.run(debug=True)