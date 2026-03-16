#!/usr/bin/env python3
"""
hipstercheck - LoRA Fine-Tuning for Code Review Model

Fine-tune Phi-2 on code review dataset using LoRA.
Generates structured reviews with severity, line_number, suggestion, explanation.
"""

import os
import json
import yaml
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model, TaskType
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeReviewTrainer:
    """Fine-tune Phi-2 for code review generation."""

    def __init__(self, config_path: str = "models/config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.model_name = self.config["model"]["name"]
        self.max_seq_length = self.config["model"]["max_seq_length"]
        self.output_dir = self.config["output"]["output_dir"]

        os.makedirs(self.output_dir, exist_ok=True)

    def load_tokenizer(self):
        """Load and configure tokenizer."""
        logger.info(f"Loading tokenizer: {self.model_name}")
        tokenizer = AutoTokenizer.from_pretrained(self.model_name)

        # Set padding token if not present
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        return tokenizer

    def load_model(self):
        """Load base model with LoRA configuration."""
        logger.info(f"Loading model: {self.model_name}")

        # Determine torch dtype
        torch_dtype_str = self.config["model"].get("torch_dtype", "float16")
        torch_dtype = torch.bfloat16 if torch_dtype_str == "bfloat16" else torch.float16

        model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            device_map="auto" if torch.cuda.is_available() else None,
        )

        # Configure LoRA
        lora_config = LoraConfig(
            r=self.config["lora"]["r"],
            lora_alpha=self.config["lora"]["lora_alpha"],
            target_modules=self.config["lora"]["target_modules"],
            lora_dropout=self.config["lora"]["lora_dropout"],
            bias=self.config["lora"]["bias"],
            task_type=TaskType.CAUSAL_LM,
        )

        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

        return model

    def prepare_dataset(self, tokenizer, split: str = "train"):
        """Load and preprocess dataset."""
        dataset_files = {
            "train": self.config["dataset"]["train_file"],
            "validation": self.config["dataset"]["validation_file"],
            "test": self.config["dataset"]["test_file"],
        }

        file_path = dataset_files.get(split)
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset file not found: {file_path}")

        logger.info(f"Loading dataset from {file_path}")

        # Load JSONL file
        with open(file_path, "r") as f:
            data = [json.loads(line) for line in f]

        # Prepare formatted examples
        formatted_data = []
        prompt_template = self.config["dataset"]["prompt_template"]
        response_template = self.config["dataset"]["response_template"]

        for item in data:
            # Extract fields
            code = item.get("code", "")
            review = item.get("review", {})
            language = item.get("language", "python")

            # Format review as JSON
            review_json = json.dumps(review, indent=2)

            # Create prompt
            prompt = prompt_template.format(code=code, language=language)
            response = response_template.format(review_json=review_json)

            # Concatenate for causal LM training
            text = prompt + response

            formatted_data.append({"text": text, "code": code, "review": review})

        logger.info(f"Prepared {len(formatted_data)} examples for {split}")

        # Tokenize
        def tokenize_function(examples):
            tokenized = tokenizer(
                examples["text"],
                truncation=True,
                padding="max_length",
                max_length=self.max_seq_length,
            )
            tokenized["labels"] = tokenized["input_ids"].copy()
            return tokenized

        from datasets import Dataset
        dataset = Dataset.from_list(formatted_data)
        tokenized_dataset = dataset.map(
            tokenize_function,
            batched=True,
            remove_columns=["text", "code", "review"],
        )

        return tokenized_dataset

    def train(self):
        """Run training loop."""
        tokenizer = self.load_tokenizer()
        model = self.load_model()

        # Prepare datasets
        train_dataset = self.prepare_dataset(tokenizer, split="train")
        eval_dataset = self.prepare_dataset(tokenizer, split="validation")

        # Training arguments
        training_args = TrainingArguments(
            output_dir=self.output_dir,
            num_train_epochs=self.config["training"]["num_train_epochs"],
            per_device_train_batch_size=self.config["training"]["per_device_train_batch_size"],
            gradient_accumulation_steps=self.config["training"]["gradient_accumulation_steps"],
            learning_rate=self.config["training"]["learning_rate"],
            warmup_steps=self.config["training"]["warmup_steps"],
            logging_dir=self.config["output"]["logging_dir"],
            logging_steps=self.config["training"]["logging_steps"],
            save_steps=self.config["training"]["save_steps"],
            eval_steps=self.config["training"]["eval_steps"],
            evaluation_strategy="steps",
            save_strategy="steps",
            load_best_model_at_end=True,
            fp16=self.config["training"]["fp16"] and torch.cuda.is_available(),
            gradient_checkpointing=self.config["training"]["gradient_checkpointing"],
            optim=self.config["training"]["optim"],
            save_total_limit=self.config["training"]["save_total_limit"],
            report_to="none",  # Disable wandb, tensorboard etc.
            push_to_hub=self.config["output"]["push_to_hub"],
        )

        # Data collator
        data_collator = DataCollatorForLanguageModeling(
            tokenizer=tokenizer,
            mlm=False,  # Causal language modeling
        )

        # Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            data_collator=data_collator,
            tokenizer=tokenizer,
        )

        # Train
        logger.info("Starting training...")
        train_result = trainer.train()

        # Save model
        logger.info(f"Saving model to {self.output_dir}")
        trainer.save_model(self.output_dir)
        tokenizer.save_pretrained(self.output_dir)

        # Save training metrics
        metrics = train_result.metrics
        metrics_file = os.path.join(self.output_dir, "train_metrics.json")
        with open(metrics_file, "w") as f:
            json.dump(metrics, f, indent=2)

        logger.info(f"Training complete. Metrics: {metrics}")
        logger.info(f"Model saved to {self.output_dir}")

        return trainer, metrics


def main():
    """Main training pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Fine-tune Phi-2 for code review")
    parser.add_argument("--config", type=str, default="models/config.yaml", help="Path to config file")
    args = parser.parse_args()

    # Check CUDA availability
    if torch.cuda.is_available():
        logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        logger.warning("No GPU detected. Training will be slow on CPU.")

    # Run training
    trainer = CodeReviewTrainer(config_path=args.config)
    trainer.train()


if __name__ == "__main__":
    main()
