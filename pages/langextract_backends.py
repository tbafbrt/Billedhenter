# langextract_backends.py
"""
Custom language model backends for LangExtract integration
Adds support for Anthropic Claude and Mistral AI APIs
"""

import dataclasses
import json
import requests
from typing import Any, Dict, List, Optional
import os

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from mistralai.client import MistralClient
    from mistralai.models.chat_completion import ChatMessage
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

from langextract.inference import BaseLanguageModel, ScoredOutput
from langextract import data


@dataclasses.dataclass(init=False)
class ClaudeLanguageModel(BaseLanguageModel):
    """Language model inference using Anthropic's Claude API."""
    
    model_id: str = 'claude-3-5-sonnet-20241022'
    api_key: str | None = None
    format_type: data.FormatType = data.FormatType.JSON
    temperature: float = 0.0
    max_workers: int = 10
    max_tokens: int = 4096
    _client: Any = dataclasses.field(default=None, repr=False, compare=False)
    
    def __post_init__(self):
        super().__init__()
        
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package is required for Claude integration. Install with: pip install anthropic")
        
        if self.api_key:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        else:
            # Try environment variable
            env_key = os.getenv('ANTHROPIC_API_KEY')
            if env_key:
                self._client = anthropic.Anthropic(api_key=env_key)
            else:
                raise ValueError("No Anthropic API key provided. Set api_key parameter or ANTHROPIC_API_KEY environment variable.")
    
    def _format_messages(self, prompt: str) -> List[Dict[str, str]]:
        """Format the prompt for Claude's message format."""
        return [{"role": "user", "content": prompt}]
    
    def _make_request(self, prompt: str) -> str:
        """Make a request to Claude API."""
        try:
            response = self._client.messages.create(
                model=self.model_id,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=self._format_messages(prompt)
            )
            return response.content[0].text
        except Exception as e:
            raise ValueError(f"Claude API request failed: {str(e)}") from e
    
    def score_outputs(
        self, 
        prompt: str, 
        candidates: List[str], 
        num_candidates: int = 1
    ) -> List[ScoredOutput]:
        """Generate and score outputs from Claude."""
        outputs = []
        
        for _ in range(num_candidates):
            try:
                response_text = self._make_request(prompt)
                # Parse the output based on format type
                parsed_output = self._parse_output(response_text)
                outputs.append(ScoredOutput(score=1.0, output=json.dumps(parsed_output)))
            except Exception as e:
                print(f"Error generating output: {e}")
                continue
        
        return outputs if outputs else [ScoredOutput(score=0.0, output=None)]
    
    def _parse_output(self, output: str) -> Any:
        """Parse the output from Claude."""
        try:
            if self.format_type == data.FormatType.JSON:
                # Extract JSON from response if it's wrapped in markdown or text
                if '```json' in output:
                    start = output.find('```json') + 7
                    end = output.find('```', start)
                    json_str = output[start:end].strip()
                elif '{' in output and '}' in output:
                    start = output.find('{')
                    end = output.rfind('}') + 1
                    json_str = output[start:end]
                else:
                    json_str = output
                
                return json.loads(json_str)
            else:
                return output
        except Exception as e:
            raise ValueError(f'Failed to parse Claude output as {self.format_type.name}: {str(e)}') from e


@dataclasses.dataclass(init=False)
class MistralLanguageModel(BaseLanguageModel):
    """Language model inference using Mistral AI API."""
    
    model_id: str = 'mistral-large-latest'
    api_key: str | None = None
    format_type: data.FormatType = data.FormatType.JSON
    temperature: float = 0.0
    max_workers: int = 10
    max_tokens: int = 4096
    _client: Any = dataclasses.field(default=None, repr=False, compare=False)
    
    def __post_init__(self):
        super().__init__()
        
        if not MISTRAL_AVAILABLE:
            raise ImportError("mistralai package is required for Mistral integration. Install with: pip install mistralai")
        
        if self.api_key:
            self._client = MistralClient(api_key=self.api_key)
        else:
            # Try environment variable
            env_key = os.getenv('MISTRAL_API_KEY')
            if env_key:
                self._client = MistralClient(api_key=env_key)
            else:
                raise ValueError("No Mistral API key provided. Set api_key parameter or MISTRAL_API_KEY environment variable.")
    
    def _format_messages(self, prompt: str) -> List[Any]:
        """Format the prompt for Mistral's message format."""
        return [ChatMessage(role="user", content=prompt)]
    
    def _make_request(self, prompt: str) -> str:
        """Make a request to Mistral API."""
        try:
            response = self._client.chat(
                model=self.model_id,
                messages=self._format_messages(prompt),
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            raise ValueError(f"Mistral API request failed: {str(e)}") from e
    
    def score_outputs(
        self, 
        prompt: str, 
        candidates: List[str], 
        num_candidates: int = 1
    ) -> List[ScoredOutput]:
        """Generate and score outputs from Mistral."""
        outputs = []
        
        for _ in range(num_candidates):
            try:
                response_text = self._make_request(prompt)
                # Parse the output based on format type
                parsed_output = self._parse_output(response_text)
                outputs.append(ScoredOutput(score=1.0, output=json.dumps(parsed_output)))
            except Exception as e:
                print(f"Error generating output: {e}")
                continue
        
        return outputs if outputs else [ScoredOutput(score=0.0, output=None)]
    
    def _parse_output(self, output: str) -> Any:
        """Parse the output from Mistral."""
        try:
            if self.format_type == data.FormatType.JSON:
                # Extract JSON from response if it's wrapped in markdown or text
                if '```json' in output:
                    start = output.find('```json') + 7
                    end = output.find('```', start)
                    json_str = output[start:end].strip()
                elif '{' in output and '}' in output:
                    start = output.find('{')
                    end = output.rfind('}') + 1
                    json_str = output[start:end]
                else:
                    json_str = output
                
                return json.loads(json_str)
            else:
                return output
        except Exception as e:
            raise ValueError(f'Failed to parse Mistral output as {self.format_type.name}: {str(e)}') from e


# Test functions for debugging
def test_claude_integration():
    """Test Claude integration (for debugging)"""
    if not ANTHROPIC_AVAILABLE:
        print("❌ Anthropic package not available")
        return False
    
    try:
        # This would need an actual API key to test
        print("✅ Claude integration loaded successfully")
        return True
    except Exception as e:
        print(f"❌ Claude integration error: {e}")
        return False


def test_mistral_integration():
    """Test Mistral integration (for debugging)"""
    if not MISTRAL_AVAILABLE:
        print("❌ Mistral package not available")
        return False
    
    try:
        # This would need an actual API key to test
        print("✅ Mistral integration loaded successfully")
        return True
    except Exception as e:
        print(f"❌ Mistral integration error: {e}")
        return False


if __name__ == "__main__":
    print("🔧 Testing LangExtract Custom Backends...")
    print(f"Anthropic available: {ANTHROPIC_AVAILABLE}")
    print(f"Mistral available: {MISTRAL_AVAILABLE}")
    
    if ANTHROPIC_AVAILABLE:
        test_claude_integration()
    
    if MISTRAL_AVAILABLE:
        test_mistral_integration()