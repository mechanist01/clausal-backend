import os
import requests
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
import tiktoken
from datetime import datetime

# Data Structure Definitions
@dataclass
class CompensationDetails:
    type: str
    amount: Optional[float]
    currency: Optional[str]
    frequency: Optional[str]
    isGuaranteed: bool

@dataclass
class CommissionStructure:
    type: str
    baseRate: float
    tiers: List[Dict[str, float]]
    caps: Dict[str, Any]

@dataclass
class CompensationTerms:
    baseCompensation: CompensationDetails
    commission: CommissionStructure

@dataclass
class TerminationTerms:
    noticePeriod: Dict[str, Any]
    immediateTerminationClauses: List[str]
    postTerminationObligations: List[str]

@dataclass
class IntellectualPropertyTerms:
    ownership: Dict[str, Any]
    moralRights: Dict[str, Any]

@dataclass
class RestrictiveCovenants:
    nonCompete: Dict[str, Any]
    nonSolicitation: Dict[str, Any]

@dataclass
class ConfidentialityTerms:
    scope: List[str]
    duration: Dict[str, Any]
    exceptions: List[str]

@dataclass
class LiabilityTerms:
    indemnification: Dict[str, Any]
    limitations: Dict[str, Any]

@dataclass
class ContractAnalysis:
    metadata: Dict[str, Any]
    classification: Dict[str, Any]
    compensation: CompensationTerms
    termination: TerminationTerms
    intellectualProperty: IntellectualPropertyTerms
    restrictiveCovenants: RestrictiveCovenants
    confidentiality: ConfidentialityTerms
    liability: LiabilityTerms

class ContractAnalyzer:
    def __init__(self):
        self.api_url = 'https://api.anthropic.com/v1/messages'
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
        }
        self.model = 'claude-3-sonnet-20240229'
        # Use cl100k_base encoding
        self.encoder = tiktoken.get_encoding('cl100k_base')

    def _chunk_text(self, text: str, max_tokens: int = 4000) -> List[str]:
        """Split text into chunks of maximum token length while preserving context."""
        try:
            # Reserve tokens for prompt
            effective_max_tokens = max_tokens - 500
            
            # Split into sentences first
            sentences = text.split('. ')
            chunks = []
            current_chunk_sentences = []
            current_chunk_tokens = 0
            
            for sentence in sentences:
                # Add period back if needed
                if sentence != sentences[-1]:
                    sentence = sentence + '.'
                    
                sentence_tokens = self.encoder.encode(sentence)
                sentence_token_count = len(sentence_tokens)
                
                # If this sentence would exceed the chunk limit
                if current_chunk_tokens + sentence_token_count > effective_max_tokens:
                    if current_chunk_sentences:
                        # Save current chunk
                        chunks.append(' '.join(current_chunk_sentences))
                        current_chunk_sentences = []
                        current_chunk_tokens = 0
                
                # Add sentence to current chunk
                current_chunk_sentences.append(sentence)
                current_chunk_tokens += sentence_token_count
            
            # Add final chunk if there's anything left
            if current_chunk_sentences:
                chunks.append(' '.join(current_chunk_sentences))
            
            logging.info(f"Split text into {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            logging.error(f"Error in text chunking: {str(e)}")
            raise

    def _analyze_chunk(self, content: str, chunk_index: int, total_chunks: int) -> Dict[str, Any]:
        """Analyze a single chunk of contract text."""
        prompt = f"""You are analyzing part {chunk_index + 1} of {total_chunks} of a contract. 
        Please analyze this section according to the following structure and output in JSON format only.
        Do not include any other text or explanation - just the JSON object.

        Contract text:
        {content}

        Important: 
        1. If this chunk doesn't contain information for certain categories, mark them as "not_found_in_chunk".
        2. All numeric values should be returned as numbers, not strings.
        3. Return your analysis as a valid JSON object.
        4. For dates, use ISO 8601 format (YYYY-MM-DD).
        5. For percentages, use decimal values (e.g., 0.20 instead of 20%).
        6. For monetary values, return the number without currency symbols.

        Expected JSON structure:
        {self._get_analysis_schema()}
        """

        try:
            logging.info(f"Analyzing chunk {chunk_index + 1}/{total_chunks}")
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={
                    'model': self.model,
                    'max_tokens': 4096,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0
                }
            )
            
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logging.error(f"Error in API call for chunk {chunk_index + 1}: {str(e)}")
            raise

    def _parse_api_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse and validate the API response content."""
        try:
            content = response['content'][0]['text']
            return json.loads(content)
        except KeyError as e:
            logging.error(f"Unexpected API response structure: {e}")
            raise ValueError("Invalid API response structure")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON content: {e}")
            raise ValueError("Invalid JSON in API response")

    def _merge_lists(self, existing: List[Any], new: List[Any]) -> List[Any]:
        """Merge two lists while removing duplicates and preserving order."""
        seen = set()
        merged = []
        for item in existing + new:
            if isinstance(item, str):
                item_key = item.lower()
            else:
                item_key = str(item)
            
            if item_key not in seen:
                seen.add(item_key)
                merged.append(item)
        return merged

    def _merge_dicts(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two dictionaries with special handling for lists."""
        merged = existing.copy()
        
        for key, new_value in new.items():
            if new_value == "not_found_in_chunk":
                continue
                
            if key not in merged:
                merged[key] = new_value
                continue
                
            if isinstance(new_value, list):
                merged[key] = self._merge_lists(merged[key], new_value)
            elif isinstance(new_value, dict):
                merged[key] = self._merge_dicts(merged[key], new_value)
            else:
                # For scalar values, prefer non-null values
                if merged[key] is None or merged[key] == "":
                    merged[key] = new_value
                    
        return merged

    def _merge_analyses(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple chunk analyses into a single comprehensive analysis."""
        if not analyses:
            raise ValueError("No analyses provided to merge")

        merged = {
            "metadata": {},
            "classification": {"type": None, "primaryCharacteristics": []},
            "compensation": {
                "baseCompensation": {},
                "commission": {"tiers": [], "caps": {}}
            },
            "termination": {
                "noticePeriod": {},
                "immediateTerminationClauses": [],
                "postTerminationObligations": []
            },
            "intellectualProperty": {
                "ownership": {},
                "moralRights": {}
            },
            "restrictiveCovenants": {
                "nonCompete": {},
                "nonSolicitation": {}
            },
            "confidentiality": {
                "scope": [],
                "duration": {},
                "exceptions": []
            },
            "liability": {
                "indemnification": {},
                "limitations": {}
            }
        }

        for analysis in analyses:
            try:
                chunk_data = self._parse_api_response(analysis)
                merged = self._merge_dicts(merged, chunk_data)
            except Exception as e:
                logging.warning(f"Error merging chunk analysis: {e}")
                continue

        return merged

    def _create_structured_analysis(self, merged_data: Dict[str, Any]) -> ContractAnalysis:
        """Create a structured ContractAnalysis object from merged data."""
        try:
            base_comp = CompensationDetails(
                type=merged_data["compensation"]["baseCompensation"].get("type"),
                amount=merged_data["compensation"]["baseCompensation"].get("amount"),
                currency=merged_data["compensation"]["baseCompensation"].get("currency"),
                frequency=merged_data["compensation"]["baseCompensation"].get("frequency"),
                isGuaranteed=merged_data["compensation"]["baseCompensation"].get("isGuaranteed", False)
            )

            commission = CommissionStructure(
                type=merged_data["compensation"]["commission"].get("type"),
                baseRate=merged_data["compensation"]["commission"].get("baseRate", 0.0),
                tiers=merged_data["compensation"]["commission"].get("tiers", []),
                caps=merged_data["compensation"]["commission"].get("caps", {"exists": False})
            )

            return ContractAnalysis(
                metadata=merged_data["metadata"],
                classification=merged_data["classification"],
                compensation=CompensationTerms(
                    baseCompensation=base_comp,
                    commission=commission
                ),
                termination=TerminationTerms(
                    noticePeriod=merged_data["termination"]["noticePeriod"],
                    immediateTerminationClauses=merged_data["termination"]["immediateTerminationClauses"],
                    postTerminationObligations=merged_data["termination"]["postTerminationObligations"]
                ),
                intellectualProperty=IntellectualPropertyTerms(
                    ownership=merged_data["intellectualProperty"]["ownership"],
                    moralRights=merged_data["intellectualProperty"]["moralRights"]
                ),
                restrictiveCovenants=RestrictiveCovenants(
                    nonCompete=merged_data["restrictiveCovenants"]["nonCompete"],
                    nonSolicitation=merged_data["restrictiveCovenants"]["nonSolicitation"]
                ),
                confidentiality=ConfidentialityTerms(
                    scope=merged_data["confidentiality"]["scope"],
                    duration=merged_data["confidentiality"]["duration"],
                    exceptions=merged_data["confidentiality"]["exceptions"]
                ),
                liability=LiabilityTerms(
                    indemnification=merged_data["liability"]["indemnification"],
                    limitations=merged_data["liability"]["limitations"]
                )
            )
        except KeyError as e:
            logging.error(f"Missing required field in merged data: {e}")
            raise ValueError(f"Incomplete contract data: missing {e}")
        except Exception as e:
            logging.error(f"Error creating structured analysis: {e}")
            raise

    def analyze_contract(self, contract_text: str) -> ContractAnalysis:
        """Analyze entire contract and return structured analysis."""
        logging.info("Starting contract analysis")
        
        chunks = self._chunk_text(contract_text)
        logging.info(f"Created {len(chunks)} chunks for analysis")
        
        analyses = []
        for i, chunk in enumerate(chunks):
            analysis = self._analyze_chunk(chunk, i, len(chunks))
            analyses.append(analysis)
            logging.info(f"Completed analysis of chunk {i + 1}/{len(chunks)}")
        
        merged_analysis = self._merge_analyses(analyses)
        structured_analysis = self._create_structured_analysis(merged_analysis)
        
        # Store original text with analysis
        structured_analysis.original_text = contract_text
        
        logging.info("Completed contract analysis")
        return structured_analysis

    def _get_analysis_schema(self) -> str:
        """Returns the JSON schema for contract analysis."""
        try:
            # Get the directory of the current file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            schema_path = os.path.join(current_dir, 'analysis_schema.json')
            
            with open(schema_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            logging.error("Schema file not found")
            raise
        except Exception as e:
            logging.error(f"Error reading schema file: {str(e)}")
            raise