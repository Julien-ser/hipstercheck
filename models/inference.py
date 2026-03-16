#!/usr/bin/env python3
"""
hipstercheck - Model Inference for Code Review

Loads fine-tuned Phi-2 model and provides inference API.
"""

import os
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel, PeftConfig
from typing import Dict, Any, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeReviewInference:
    """Inference wrapper for code review model."""

    def __init__(self, model_path: str = "models/checkpoints/phi2-code-review"):
        self.model_path = model_path
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = None
        self.model = None
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load prompt template from config or default."""
        config_path = os.path.join(self.model_path, "config.yaml")
        if os.path.exists(config_path):
            import yaml
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            return config["dataset"]["prompt_template"]
        else:
            # Default template
            return """Analyze this code and provide a code review:
[Language: {language}]

Code:
{code}

Provide a review in JSON format with the following fields:
{
  "severity": "high|medium|low",
  "line_number": <int>,
  "category": "bug|optimization|style|security|best_practice",
  "suggestion": "<concise suggestion>",
  "explanation": "<detailed explanation>",
  "code_example": "<optional corrected code>"
}

Review:"""

    def load(self):
        """Load the fine-tuned model and tokenizer."""
        logger.info(f"Loading model from {self.model_path}")

        # Check if it's a LoRA checkpoint
        config_path = os.path.join(self.model_path, "adapter_config.json")
        if os.path.exists(config_path):
            # LoRA model - need base model
            peft_config = PeftConfig.from_pretrained(self.model_path)
            base_model_path = peft_config.base_model_name_or_path

            logger.info(f"Loading base model: {base_model_path}")
            tokenizer = AutoTokenizer.from_pretrained(base_model_path)
            model = AutoModelForCausalLM.from_pretrained(
                base_model_path,
                torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True,
            )
            model = PeftModel.from_pretrained(model, self.model_path)
        else:
            # Fully merged model
            tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True,
            )

        # Set padding token
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model.eval()
        self.tokenizer = tokenizer
        self.model = model

        logger.info("Model loaded successfully")
        return self

    def generate_review(self, code: str, language: str = "python", max_new_tokens: int = 512) -> Dict[str, Any]:
        """
        Generate code review for given code snippet.

        Args:
            code: Source code to review
            language: Programming language (python, cpp, etc.)
            max_new_tokens: Maximum tokens to generate

        Returns:
            Dictionary with review fields: severity, line_number, category, suggestion, explanation, code_example
        """
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Create prompt
        prompt = self.prompt_template.format(code=code, language=language)

        # Tokenize
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.2,
                top_p=0.95,
                do_sample=False,  # Use greedy decoding for consistency
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # Decode response
        full_output = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        response_start = full_output.find("Review:") + len("Review:")
        response_text = full_output[response_start:].strip()

        # Parse JSON from response
        try:
            # Find JSON object in response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end]
                review = json.loads(json_str)
            else:
                # Fallback: try to parse entire response
                review = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text}")
            review = {
                "severity": "unknown",
                "line_number": 0,
                "category": "parsing_error",
                "suggestion": "Model output could not be parsed as JSON",
                "explanation": response_text[:500],
                "code_example": None,
            }

        return review

    def batch_generate(self, code_snippets: list, language: str = "python") -> list:
        """Generate reviews for multiple code snippets."""
        reviews = []
        for code in code_snippets:
            review = self.generate_review(code, language)
            reviews.append(review)
        return reviews


if __name__ == "__main__":
    # Quick test
    import argparse

    parser = argparse.ArgumentParser(description="Test code review inference")
    parser.add_argument("--model_path", type=str, default="models/checkpoints/phi2-code-review")
    parser.add_argument("--code_file", type=str, help="Path to code file to review")
    args = parser.parse_args()

    inference = CodeReviewInference(model_path=args.model_path)
    inference.load()

    if args.code_file:
        with open(args.code_file, "r") as f:
            code = f.read()
    else:
        code = """
def compute(x, y):
    temp = x + y
    return x * y
"""

    review = inference.generate_review(code)
    print(json.dumps(review, indent=2))
