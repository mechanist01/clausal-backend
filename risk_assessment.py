# risk_assessment.py
import os
import aiohttp
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List
from datetime import datetime
import json
import traceback

@dataclass
class Risk:
    title: str
    description: str
    severity: str  # 'high', 'medium', 'low'
    category: str  # matches the sections in analysis schema
    recommendation: Optional[str] = None

@dataclass
class RiskAssessmentResult:
    risks: List[Risk]
    summary: Dict
    timestamp: str

class ContractRiskAssessor:
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
        self._init_storage()
        logging.info("ContractRiskAssessor initialized successfully")

    def _init_storage(self):
        """Initialize storage for risk assessment results."""
        self.storage_dir = 'risk_assessments'
        os.makedirs(self.storage_dir, exist_ok=True)

    def _save_assessment(self, contract_id: str, assessment: RiskAssessmentResult):
        """Save risk assessment to disk."""
        try:
            file_path = os.path.join(self.storage_dir, f'{contract_id}_risks.json')
            with open(file_path, 'w') as f:
                json.dump(asdict(assessment), f, indent=2)
        except Exception as e:
            logging.error(f"Error saving risk assessment: {str(e)}")

    def _load_assessment(self, contract_id: str) -> Optional[RiskAssessmentResult]:
        """Load existing risk assessment if available."""
        try:
            file_path = os.path.join(self.storage_dir, f'{contract_id}_risks.json')
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    return RiskAssessmentResult(**data)
        except Exception as e:
            logging.error(f"Error loading risk assessment: {str(e)}")
        return None

    async def assess_risks(self, contract_analysis: Dict) -> RiskAssessmentResult:
        """Analyze contract for risks using Claude."""
        try:
            logging.info("Starting risk assessment")
            
            # Prepare the prompt
            prompt = f"""You are a contract risk assessment expert. Analyze this contract and identify potential risks 
            and concerns from the contractor/employee's perspective.

            Contract Analysis:
            {json.dumps(contract_analysis, indent=2)}

            For each identified risk:
            1. Categorize into one of these categories: compensation, termination, ip, covenants, confidentiality, liability
            2. Assign severity (high, medium, low)
            3. Provide clear description of the risk
            4. Include specific recommendation to address or mitigate the risk

            Format your response exactly like this example:
            {{
                "risks": [
                    {{
                        "title": "Long Non-Compete Duration",
                        "description": "The non-compete clause extends for 2 years, which is longer than industry standard.",
                        "severity": "high",
                        "category": "covenants",
                        "recommendation": "Negotiate to reduce the non-compete period to 6-12 months"
                    }},
                    {{
                        "title": "Broad IP Assignment",
                        "description": "All intellectual property, including personal projects, may be claimed by the company.",
                        "severity": "high",
                        "category": "ip",
                        "recommendation": "Add exclusions for pre-existing work and personal projects"
                    }}
                ]
            }}

            IMPORTANT: Return only the JSON object, no other text."""

            logging.info("Sending request to Claude")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.anthropic.com/v1/messages',
                    headers=self.headers,
                    json={
                        'model': self.model,
                        'max_tokens': 4000,
                        'messages': [{'role': 'user', 'content': prompt}]
                    }
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logging.error(f"Claude API error: {error_text}")
                        raise Exception(f"API error: {error_text}")
                    
                    result = await response.json()
                    assessment_text = result['content'][0]['text']
                    logging.info(f"Received response from Claude: {assessment_text[:200]}")
                    
                    try:
                        assessment_data = json.loads(assessment_text)
                    except json.JSONDecodeError as e:
                        logging.error(f"Failed to parse Claude's response: {assessment_text}")
                        logging.error(f"JSON error: {str(e)}")
                        raise

                    # Verify response structure
                    if not isinstance(assessment_data, dict) or 'risks' not in assessment_data:
                        logging.error(f"Unexpected response structure: {assessment_data}")
                        raise ValueError("Invalid response structure from Claude")

                    # Create summary
                    risks = assessment_data['risks']
                    summary = {
                        'totalRisks': len(risks),
                        'highPriorityCount': len([r for r in risks if r['severity'] == 'high']),
                        'mediumPriorityCount': len([r for r in risks if r['severity'] == 'medium']),
                        'lowPriorityCount': len([r for r in risks if r['severity'] == 'low']),
                        'risksByCategory': {}
                    }

                    # Group risks by category
                    for risk in risks:
                        category = risk['category']
                        if category not in summary['risksByCategory']:
                            summary['risksByCategory'][category] = []
                        summary['risksByCategory'][category].append(risk)

                    assessment_result = RiskAssessmentResult(
                        risks=risks,
                        summary=summary,
                        timestamp=datetime.now().isoformat()
                    )

                    # Save the assessment
                    contract_id = contract_analysis.get('metadata', {}).get('id', 'unknown')
                    self._save_assessment(contract_id, assessment_result)

                    return assessment_result

        except Exception as e:
            logging.error(f"Error in risk assessment: {str(e)}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def get_cached_assessment(self, contract_id: str) -> Optional[RiskAssessmentResult]:
        """Get cached risk assessment if available."""
        return self._load_assessment(contract_id)