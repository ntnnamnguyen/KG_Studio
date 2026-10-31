"""Chuẩn bị tập dữ liệu SFT & sinh kịch bản huấn luyện QLoRA (Unsloth / HuggingFace TRL)."""
from __future__ import annotations

import json
from pathlib import Path

from backend.integrations.embedder_gateway import MODEL_REGISTRY_DIR
from shared.text_utils import now_iso, slug


def generate_lora_training_bundle(
    sft_dataset_path: str | Path,
    adapter_name: str = "qwen-kg-lora-v1",
    *,
    base_model: str = "Qwen/Qwen2.5-7B-Instruct",
    registry_dir: Path | None = None,
) -> dict:
    src = Path(sft_dataset_path)
    records = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()] if src.exists() else []

    target_registry = registry_dir or MODEL_REGISTRY_DIR
    safe_folder = slug(adapter_name)
    out_dir = target_registry / safe_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    chat_rows: list[dict] = []
    for rec in records:
        chat_rows.append(
            {
                "messages": [
                    {"role": "system", "content": rec.get("system_prompt", "")},
                    {"role": "user", "content": rec.get("chunk_text", "")},
                    {"role": "assistant", "content": json.dumps(rec.get("target_json", {}), ensure_ascii=False)},
                ]
            }
        )

    chat_file = out_dir / "sft_chatml_dataset.jsonl"
    chat_file.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in chat_rows) + ("\n" if chat_rows else ""),
        encoding="utf-8",
    )

    train_script = f'''"""Kịch bản Fine-tune QLoRA tự động sinh bởi KG Studio ML Lab."""
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from trl import SFTTrainer

BASE_MODEL = "{base_model}"
DATASET_FILE = r"{chat_file}"
OUTPUT_DIR = r"{out_dir / 'lora_adapter'}"

def main():
    dataset = load_dataset("json", data_files=DATASET_FILE, split="train")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, device_map="auto", trust_remote_code=True)
    peft_config = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        tokenizer=tokenizer,
        args=TrainingArguments(output_dir=OUTPUT_DIR, num_train_epochs=3, per_device_train_batch_size=2),
    )
    trainer.train()
    trainer.model.save_pretrained(OUTPUT_DIR)

if __name__ == "__main__":
    main()
'''
    script_path = out_dir / "run_qlora_train.py"
    script_path.write_text(train_script, encoding="utf-8")

    metadata = {
        "model_id": f"lora:{safe_folder}",
        "name": f"LLM LoRA Bundle ({adapter_name})",
        "task": "sft_llm_lora",
        "base_model": base_model,
        "created_at": now_iso(),
        "sft_samples": len(chat_rows),
        "dataset_path": str(chat_file),
        "script_path": str(script_path),
    }
    (out_dir / "lora_bundle_meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata

