#!/usr/bin/env python3
"""Generate the LLM outputs used by Experiment 1 and the encoding experiment.

Runs Qwen2.5-1.5B-Instruct locally at a pinned Hugging Face revision on the
CPU in float32, with the sampling settings from the model's own
generation_config.json and a fixed seed per prompt (SEED + prompt index).
Writes data/exp1_generations.jsonl (one GenerationRecord per line, plus the
prompt id) and data/exp1_generation_meta.json (library versions, device).

The outputs are committed to the repository, so the chain experiments can be
rerun without a GPU or the model. Regenerating them on different hardware or
library versions may give different text, because floating-point results are
not identical across platforms.

Install the extra dependencies first: pip install -r requirements-llm.txt
The model (about 3 GB, safetensors) is downloaded to the Hugging Face cache on
first use.
"""

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provenance.record import GenerationRecord

DATA = ROOT / "data"
MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"  # main as of 2024-09-25
SEED = 435
# Same values as the model's generation_config.json, written out so that they
# are part of every committed record.
SAMPLING = {"do_sample": True, "temperature": 0.7, "top_p": 0.8, "top_k": 20, "repetition_penalty": 1.1, "max_new_tokens": 256}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    prompts = json.loads((DATA / "exp1_prompts.json").read_text(encoding="utf-8"))["prompts"]
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModelForCausalLM.from_pretrained(MODEL, revision=REVISION, dtype=torch.float32, use_safetensors=True)
    model.eval()

    lines = []
    for index, prompt in enumerate(prompts):
        seed = SEED + index
        transformers.set_seed(seed)
        chat = tokenizer.apply_chat_template([{"role": "user", "content": prompt["text"]}], add_generation_prompt=True, return_tensors="pt", return_dict=True)
        with torch.no_grad():
            generated = model.generate(**chat, **SAMPLING, pad_token_id=tokenizer.eos_token_id)
        output = tokenizer.decode(generated[0, chat["input_ids"].shape[1]:], skip_special_tokens=True)
        params = {key: value for key, value in SAMPLING.items() if key != "do_sample"} | {"seed": seed, "revision": REVISION}
        record = GenerationRecord(model=MODEL, prompt=prompt["text"], output=output, params=params, created_at=utc_now())
        lines.append(json.dumps({"id": prompt["id"], "kind": prompt["kind"], "record": json.loads(record.to_json())}, ensure_ascii=False))
        print(f"{prompt['id']} ({len(output)} chars): {output[:70]!r}", flush=True)

    (DATA / "exp1_generations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DATA / "exp1_generation_meta.json").write_text(json.dumps({
        "model": MODEL,
        "revision": REVISION,
        "seed": SEED,
        "sampling": SAMPLING,
        "device": "cpu",
        "dtype": "float32",
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "date": datetime.now(timezone.utc).date().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
