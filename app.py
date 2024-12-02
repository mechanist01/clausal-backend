from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename
import os
import hashlib
import json
from datetime import datetime
import logging
from contract_chat import ChatMessage
import PyMuPDF  # PyMuPDF
from datetime import datetime, timezone, UTC
from dotenv import load_dotenv
from contract_analyzer import ContractAnalyzer
from dataclasses import asdict
from contract_chat import ContractChat
from risk_assessment import ContractRiskAssessor
import traceback
import asyncio
from functools import wraps
from supabase import create_client
from auth import requires_auth, AuthError
from jose import jwt  # New import for JWT handling
from dotenv import load_dotenv
import uuid  # New import for UUID generation
load_dotenv()  # Add this before accessing environment variables

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
CORS(app, 
     resources={r"/*": {
         "origins": "http://localhost:3000",  # Single origin instead of list
         "supports_credentials": True,
         "allow_headers": ["Content-Type", "Authorization"],
         "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
     }})

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin and origin == 'http://localhost:3000':
        response.headers.add('Access-Control-Allow-Origin', origin)
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    if request.method == 'OPTIONS':
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        response.headers.add('Access-Control-Max-Age', '3600')
    return response

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

# Initialize handlers
risk_assessor = ContractRiskAssessor()
chat_handler = ContractChat()

SUPABASE_URL = "https://pfxdwmwwfmxiqnjworyc.supabase.co"
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Initialize Supabase without auth header first
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

AUTH0_CLIENT_SECRET = os.getenv('AUTH0_CLIENT_SECRET')

def get_user_id_from_token(auth_header):
    """Extract user ID from Auth0 token"""
    try:
        token = auth_header.split(' ')[1]
        payload = jwt.get_unverified_claims(token)
        return payload['sub']  # Auth0 user ID
    except Exception as e:
        logging.error(f"Error extracting user ID: {e}")
        raise AuthError({"code": "invalid_token",
                        "description": "Could not parse user ID from token"}, 401)

# Helper function to run async code in Flask
def async_route(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from PDF file."""
    logging.info(f"Starting PDF text extraction from {file_path}")
    try:
        doc = PyMuPDF.open(file_path)
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

@app.route('/analyze', methods=['POST', 'OPTIONS'])
@requires_auth
def analyze_contract():
    """Endpoint for analyzing contract documents."""
    logging.info("Starting contract analysis request")
    file_path = None
    
    try:
        # Get user ID from token
        auth_header = request.headers.get('Authorization')
        auth0_user_id = get_user_id_from_token(auth_header)
        logging.info(f"Processing request for Auth0 user: {auth0_user_id}")
        
        # Query auth.users instead of public.users
        user_query = supabase.rpc('get_auth_user', {'auth0_id': auth0_user_id}).execute()
        user_uuid = None

        if user_query.data:
            user_uuid = user_query.data[0]['id']
            logging.info(f"Found existing user: {user_uuid}")
        else:
            # Create new user with RPC call
            user_uuid = str(uuid.uuid4())
            user_data = {
                'id': user_uuid,
                'auth0_user_id': auth0_user_id,
                'raw_user_meta_data': {
                    'auth0_id': auth0_user_id
                },
                'is_anonymous': False,
                'is_sso_user': True
            }
            
            # Use RPC to create auth user
            supabase.rpc('create_auth_user', {'user_data': user_data}).execute()
            logging.info(f"Created new user: {user_uuid}")

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
            
            # Extract and analyze content
            file_content = extract_text_from_pdf(file_path)
            analyzer = ContractAnalyzer()
            analysis_result = analyzer.analyze_contract(file_content)
            
            # Prepare metadata
            current_time = datetime.now(UTC).isoformat()
            file_size = os.path.getsize(file_path)
            
            metadata = {
                'timestamp': current_time,
                'filesize': file_size,
                'analysis_version': '1.0',
                'file_hash': hashlib.md5(file_content.encode()).hexdigest()
            }
            
            # Create contract record
            contract_data = {
                'filename': filename,
                'user_id': user_uuid,
                'metadata': metadata,
                'created_at': current_time,
            }
            
            logging.info(f"Creating contract for user {user_uuid}")
            contract = supabase.from_('contracts').insert(contract_data).execute()
            
            if not contract.data:
                raise Exception("Failed to create contract record")
                
            contract_id = contract.data[0]['id']
            
            # Store analysis results
            analysis_data = {
                'contract_id': contract_id,
                'analysis': asdict(analysis_result),
                'created_at': current_time
            }
            
            supabase.from_('analysis_results').insert(analysis_data).execute()
            logging.info(f"Stored analysis results for contract {contract_id}")

            return jsonify({
                'status': 'success',
                'contractId': contract_id,
                'analysis': asdict(analysis_result),
                'metadata': metadata
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

@app.route('/contractIQ', methods=['POST'])
@requires_auth
@async_route
async def chat_with_contract():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No request data provided'}), 400

        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'No authorization header'}), 401

        # Get user ID from token
        try:
            auth0_user_id = get_user_id_from_token(auth_header)
            logging.info(f"Auth0 user ID: {auth0_user_id}")
            
            # Query for user UUID from auth0_user_id
            user_query = supabase.rpc('get_auth_user', {'auth0_id': auth0_user_id}).execute()
            if not user_query.data:
                logging.error(f"User not found for auth0_id: {auth0_user_id}")
                return jsonify({'error': 'User not found'}), 404
                
            user_uuid = user_query.data[0]['id']
            logging.info(f"Found user UUID: {user_uuid}")
            
        except Exception as e:
            logging.error(f"Error processing user authentication: {str(e)}")
            return jsonify({'error': 'Authentication failed'}), 401
        
        # Validate required fields
        if 'message' not in data or 'contractId' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        # Query the contract with user verification
        contract_query = supabase.from_('contracts').select('*').eq('id', data['contractId']).execute()
        
        if not contract_query.data or len(contract_query.data) == 0:
            return jsonify({'error': 'Contract not found'}), 404

        contract = contract_query.data[0]
        
        # Verify user owns the contract
        if str(contract.get('user_id')) != str(user_uuid):
            logging.warning(f"Access denied: User {user_uuid} attempted to access contract {data['contractId']}")
            return jsonify({'error': 'You do not have permission to access this contract'}), 403

        # Query analysis results for contract text
        analysis_query = supabase.from_('analysis_results').select('*').eq('contract_id', data['contractId']).execute()
        
        if not analysis_query.data or len(analysis_query.data) == 0:
            return jsonify({'error': 'Contract analysis not found'}), 404

        # Look up the file using the filename from the contract record
        contract_path = os.path.join(app.config['UPLOAD_FOLDER'], contract['filename'])
        logging.info(f"Looking for contract at: {contract_path}")

        if not os.path.exists(contract_path):
            logging.error(f"Contract file not found at: {contract_path}")
            return jsonify({'error': 'Contract file not found'}), 404

        # Get chat history
        chat_history = chat_handler.chat_histories.get(data['contractId'], [])

        try:
            # Always extract text for first message or if context is missing
            contract_text = None
            if not chat_history or data['contractId'] not in chat_handler.contract_contexts:
                logging.info("Loading contract text")
                try:
                    contract_text = extract_text_from_pdf(contract_path)
                    logging.info(f"Successfully extracted {len(contract_text)} characters from contract")
                    # Store the contract text in the context
                    if data['contractId'] not in chat_handler.contract_contexts:
                        chat_handler.contract_contexts[data['contractId']] = {
                            'contract_text': contract_text,
                            'system_prompt': """You are an expert contract analyst assistant. You have been provided with a contract to analyze. 
                            When responding to questions:
                            1. Always refer to specific sections of the contract when relevant
                            2. Quote the exact text when making important points
                            3. Be clear about what the contract explicitly states vs what is implied
                            4. If something is not addressed in the contract, say so explicitly
                            5. Provide balanced analysis considering both parties' perspectives
                            6. Use clear, professional language
                            7. Focus on accuracy and precision in your interpretations"""
                        }
                        logging.info(f"Stored contract text in context for {data['contractId']}")
                except Exception as e:
                    logging.error(f"Failed to extract text from PDF: {str(e)}")
                    return jsonify({'error': 'Failed to read contract file'}), 500
            else:
                logging.info("Using existing contract context")
                contract_text = chat_handler.contract_contexts[data['contractId']]['contract_text']
                logging.info(f"Retrieved contract text from context, length: {len(contract_text)}")

            # Get the response from chat handler
            response = await chat_handler.get_response(
                message=data['message'],
                contract_id=data['contractId'],
                contract_text=contract_text,
                chat_history=chat_history
            )

            # Store the chat message in Supabase
            chat_message = {
                'contract_id': data['contractId'],
                'user_id': user_uuid,
                'role': response.role,
                'content': response.content,
                'created_at': datetime.now().isoformat(),
                'contract_reference': response.contractReference if hasattr(response, 'contractReference') else None
            }

            try:
                # Store message in Supabase
                supabase.from_('chat_messages').insert(chat_message).execute()
            except Exception as e:
                logging.error(f"Failed to store chat message in Supabase: {str(e)}")
                # Continue with response even if storage fails
            
            # Format response
            return jsonify({
                'id': str(datetime.now().timestamp()),  # Updated to use timestamp as ID
                'role': response.role,
                'content': response.content,
                'contractReference': response.contractReference if hasattr(response, 'contractReference') else None,
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            logging.error(f"Chat processing error: {str(e)}")
            logging.error(traceback.format_exc())
            return jsonify({
                'error': 'Failed to process chat message',
                'details': str(e)
            }), 500

    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        logging.error(traceback.format_exc())
        return jsonify({
            'error': 'Server error',
            'details': str(e)
        }), 500

@app.route('/riskassess', methods=['POST'])
@requires_auth
@async_route
async def assess_contract_risks():
    try:
        data = request.get_json()
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'No authorization header'}), 401

        # Get user ID from token
        auth0_user_id = get_user_id_from_token(auth_header)
        contract_id = data.get('contract_id')

        # Query Supabase for the analysis results
        analysis_query = supabase.from_('analysis_results') \
            .select('*') \
            .eq('contract_id', contract_id) \
            .single() \
            .execute()
        
        if not analysis_query.data:
            return jsonify({'error': 'Analysis results not found'}), 404

        # If risk assessment already exists, return it
        if analysis_query.data.get('risk_assessment'):
            logging.info(f"Found existing risk assessment for contract {contract_id}")
            return jsonify(analysis_query.data['risk_assessment'])

        # Assess risks using the analysis data
        assessment_result = await risk_assessor.assess_risks(analysis_query.data['analysis'])
        
        # Save risk assessment back to analysis_results
        update_query = supabase.from_('analysis_results') \
            .update({
                'risk_assessment': asdict(assessment_result)
            }) \
            .eq('contract_id', contract_id) \
            .execute()

        if update_query.error:
            raise Exception(f"Failed to save risk assessment: {update_query.error}")

        return jsonify(asdict(assessment_result))

    except Exception as e:
        logging.error(f"Error in risk assessment: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file size limit exceeded error."""
    return jsonify({
        'error': 'File too large',
        'details': 'The file size exceeds the maximum allowed limit of 16MB'
    }), 413

# Add error handler
@app.errorhandler(AuthError)
def handle_auth_error(ex):
    return jsonify(ex.error), ex.status_code

if __name__ == '__main__':
    logging.info("Starting Flask server...")
    app.run(debug=True, host='0.0.0.0', port=5000)