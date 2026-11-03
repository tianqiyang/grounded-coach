"""One tiny live call to confirm the key, model name and structured output work (~$0.001).

    python3 scripts/smoke_live.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from grounded.meta_client import make_client  # noqa: E402

client = make_client(ROOT)
if not client.live:
    sys.exit("META_API_KEY is not set. Copy .env.example to .env and add your key.")
schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "model_says": {"type": "string"}},
          "required": ["ok", "model_says"], "additionalProperties": False}
out, meta = client.chat_json("smoke", [{"role": "user", "content": "Reply with ok=true and a five-word greeting."}],
                             schema, max_out=300, reasoning="minimal")
print("response:", out)
print(f"model={meta['model']} cost=${meta['cost_usd']:.6f} seconds={meta['seconds']} usage={meta['usage']}")
print(f"ledger total ${client.ledger.spent():.4f} of ${client.ledger.cap:.2f}")
