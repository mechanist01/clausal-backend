# contract_chat.py
import os
import requests
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List
from datetime import datetime
import json
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS
from claude_embeddings import ClaudeEmbeddings

@dataclass
class ChatMessage:
    id: str
    role: str
    content: str
    timestamp: str
    contractReference: Optional[Dict[str, str]] = None

@dataclass
class ChatHistory:
    contract_id: str
    messages: List[ChatMessage]

class ContractChat:
    def __init__(self):
        self.api_url = 'https://api.anthropic.com/v1/messages'
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = 'claude-3-sonnet-20240229'
        self.headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
        }
        self.embeddings = ClaudeEmbeddings(os.getenv('ANTHROPIC_API_KEY'))
        self.vector_stores = {}
        self.chat_histories = {}
        self._init_storage()

    def _init_storage(self):
        storage_dir = 'chat_storage'
        os.makedirs(storage_dir, exist_ok=True)
        
        # Load existing chat histories
        history_file = os.path.join(storage_dir, 'chat_histories.json')
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                histories = json.load(f)
                for contract_id, messages in histories.items():
                    self.chat_histories[contract_id] = messages

    def _save_chat_history(self, contract_id: str, messages: List[Dict]):
        self.chat_histories[contract_id] = messages
        storage_dir = 'chat_storage'
        history_file = os.path.join(storage_dir, 'chat_histories.json')
        
        with open(history_file, 'w') as f:
            json.dump(self.chat_histories, f)

    def _create_vector_store(self, contract_id: str, text: str):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )
        chunks = text_splitter.split_text(text)
        
        vector_store = FAISS.from_texts(
            texts=chunks,
            embedding=self.embeddings
        )
        self.vector_stores[contract_id] = vector_store

    def _get_relevant_context(self, contract_id: str, query: str, k: int = 3) -> str:
        if contract_id not in self.vector_stores:
            return ""
        
        vector_store = self.vector_stores[contract_id]
        relevant_chunks = vector_store.similarity_search(query, k=k)
        return "\n".join(doc.page_content for doc in relevant_chunks)

    def _get_chat_prompt(self, contract_text: str, message: str, relevant_context: str, chat_history: List[Dict] = None) -> str:
        history_context = ""
        if chat_history:
            history_context = "Previous conversation:\n" + "\n".join(
                f"{msg['role']}: {msg['content']}" for msg in chat_history[-3:]
            ) + "\n\n"

        return f"""You are analyzing a contract and helping answer questions about it. Use the following information:

        {history_context}
        Relevant Contract Sections:
        {relevant_context}

        Full Contract Text (for reference):
        {contract_text}

        User Question: {message}

        Quote specific sections when referencing the contract."""

    def get_response(self, message: str, contract_id: str, contract_text: str, chat_history: List[Dict] = None) -> ChatMessage:
        try:
            # Initialize vector store if needed
            if contract_id not in self.vector_stores:
                self._create_vector_store(contract_id, contract_text)

            # Get relevant context
            relevant_context = self._get_relevant_context(contract_id, message)
            
            prompt = self._get_chat_prompt(contract_text, message, relevant_context, chat_history)
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={
                    'model': self.model,
                    'max_tokens': 1000,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.7
                }
            )
            
            response.raise_for_status()
            assistant_message = response.json()['content'][0]['text']

            # Create chat message
            chat_message = ChatMessage(
                id=str(datetime.now().timestamp()),
                role='assistant',
                content=assistant_message,
                timestamp=datetime.now().isoformat()
            )

            # Update chat history
            if not chat_history:
                chat_history = []
            chat_history.append(asdict(chat_message))
            self._save_chat_history(contract_id, chat_history)

            return chat_message

        except Exception as e:
            logging.error(f"Error getting chat response: {str(e)}")
            raise