# contract_chat.py
import os
import aiohttp
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List
from datetime import datetime
import json

@dataclass
class ChatMessage:
    id: str
    role: str
    content: str
    timestamp: str
    contractReference: Optional[Dict[str, str]] = None

class ContractChat:
    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
            
        self.model = 'claude-3-sonnet-20240229'
        self.headers = {
            'anthropic-version': '2023-06-01',
            'x-api-key': self.api_key,
            'content-type': 'application/json',
        }
        self.chat_histories = {}
        self.contract_contexts = {}
        self._init_storage()
        logging.info("ContractChat initialized successfully")

    def _init_storage(self):
        """Initialize storage for chat histories."""
        storage_dir = 'chat_storage'
        os.makedirs(storage_dir, exist_ok=True)
        history_file = os.path.join(storage_dir, 'chat_histories.json')
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                self.chat_histories = json.load(f)

    def _save_chat_history(self, contract_id: str, messages: List[Dict]):
        """Save chat history to disk."""
        try:
            self.chat_histories[contract_id] = messages
            storage_dir = 'chat_storage'
            history_file = os.path.join(storage_dir, 'chat_histories.json')
            with open(history_file, 'w') as f:
                json.dump(self.chat_histories, f)
        except Exception as e:
            logging.error(f"Error saving chat history: {str(e)}")

    async def get_response(
        self, 
        message: str, 
        contract_id: str, 
        contract_text: str, 
        chat_history: List[Dict] = None
    ) -> ChatMessage:
        """Get a response from the contract expert."""
        try:
            logging.info(f"Processing message for contract {contract_id}")
            logging.info(f"Contract text exists: {bool(contract_text)}")
            if contract_text:
                logging.info(f"Contract text length: {len(contract_text)}")
                logging.info(f"First 500 chars of contract: {contract_text[:500] if contract_text else 'None'}")
            
            if contract_id not in self.contract_contexts:
                logging.info("Setting up new contract context")
                logging.info(f"Initializing with contract text length: {len(contract_text) if contract_text else 0}")
                self.contract_contexts[contract_id] = {
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
            else:
                logging.info("Using existing contract context")
                logging.info(f"Existing context contract text length: {len(self.contract_contexts[contract_id]['contract_text'])}")

            messages = []
            logging.info("=== Building Message History ===")
            
            if not chat_history or contract_id not in self.contract_contexts:
                logging.info("Starting new conversation with contract")
                messages.append({
                    'role': 'user',
                    'content': f"Here is the contract to analyze:\n\n{contract_text}\n\nPlease acknowledge that you've received the contract."
                })
                messages.append({
                    'role': 'assistant',
                    'content': "I have received the contract and am ready to help analyze it. What would you like to know about the contract?"
                })
            
            if chat_history:
                logging.info(f"Adding {len(chat_history[-3:])} messages from history")
                for msg in chat_history[-3:]:
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
            
            if messages and messages[0]['role'] != 'user':
                logging.info("Adding contract text for context")
                messages.insert(0, {
                    'role': 'user',
                    'content': f"Here is the contract to analyze:\n\n{self.contract_contexts[contract_id]['contract_text']}\n\nPlease analyze this contract."
                })
            
            messages.append({
                'role': 'user',
                'content': message
            })
            logging.info(f"Added current user message: {message}")

            logging.info("=== Preparing Claude API Request ===")
            request_data = {
                'model': self.model,
                'max_tokens': 1000,
                'messages': messages,
                'system': self.contract_contexts[contract_id]['system_prompt'],
                'temperature': 0.7
            }
            logging.info(f"Message count in request: {len(messages)}")
            logging.info(f"First message role: {messages[0]['role']}")
            logging.info(f"First message content length: {len(messages[0]['content'])}")

            logging.info("Sending request to Claude")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.anthropic.com/v1/messages',
                    headers=self.headers,
                    json=request_data
                ) as response:
                    response_text = await response.text()
                    logging.info(f"Got response from Claude: {response.status}")
                    
                    if response.status != 200:
                        error_msg = f"Claude API error: {response_text}"
                        logging.error(error_msg)
                        raise ValueError(error_msg)
                    
                    try:
                        result = json.loads(response_text)
                        if not result.get('content') or not isinstance(result['content'], list):
                            raise ValueError("Invalid response format: missing content array")
                            
                        content_item = result['content'][0]
                        if not content_item.get('text'):
                            raise ValueError("Invalid response format: missing text in content")
                            
                        assistant_message = content_item['text']
                        logging.info("Successfully processed Claude's response")
                        logging.info(f"Response length: {len(assistant_message)}")

                        chat_message = ChatMessage(
                            id=str(datetime.now().timestamp()),
                            role='assistant',
                            content=assistant_message,
                            timestamp=datetime.now().isoformat()
                        )

                        if not chat_history:
                            chat_history = []
                        chat_history.append(asdict(chat_message))
                        self._save_chat_history(contract_id, chat_history)

                        return chat_message
                        
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        error_msg = f"Error parsing Claude response: {str(e)}"
                        logging.error(f"{error_msg}. Response text: {response_text}")
                        raise ValueError(error_msg)

        except Exception as e:
            logging.error(f"Error in get_response: {str(e)}")
            raise ValueError(f"Failed to process chat message: {str(e)}")