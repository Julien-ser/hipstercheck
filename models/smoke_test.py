#!/usr/bin/env python3
"""
Smoke test for training pipeline components.

Tests model loading, LoRA application, and forward pass
using a tiny dataset. Does not run full training to keep runtime short.
"""

import os
import sys
import tempfile
import json
import torch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model, TaskType


def test_components():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        print("🚀 Component smoke test")
        model_name = "microsoft/phi-2"
        print(f"  Model: {model_name}")
        print(f"  Device: CPU (GPU not available)")

        try:
            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_name, trust_remote_code=True
            )
            tokenizer.pad_token = tokenizer.eos_token
            print("✅ Tokenizer loaded")

            # Load model (use float16 to reduce memory)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            )
            print("✅ Model loaded")

            # Apply LoRA with phi-2 compatible target modules
            lora_config = LoraConfig(
                r=16,
                lora_alpha=32,
                target_modules=["q_proj", "k_proj", "v_proj", "dense", "fc1", "fc2"],
                lora_dropout=0.1,
                bias="none",
                task_type=TaskType.CAUSAL_LM,
            )
            model = get_peft_model(model, lora_config)
            model.print_trainable_parameters()
            print("✅ LoRA applied")

            # Create dummy input for forward pass test
            dummy_code = "def add(a, b):\n    return a + b"
            inputs = tokenizer(
                dummy_code, return_tensors="pt", truncation=True, max_length=128
            )
            inputs = {k: v.to("cpu") for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)

            assert outputs.logits.shape[0] == 1
            print(f"✅ Forward pass successful (logits shape: {outputs.logits.shape})")

            print("\n🎉 All checks passed! Fine-tuning pipeline is ready.")
            return 0

        except Exception as e:
            print(f"❌ Smoke test failed: {e}")
            import traceback

            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(test_components())
