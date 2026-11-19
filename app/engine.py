"""Coding engine: sends clinical text to the fine-tuned model (served by Ollama),
then checks the suggested codes with the ICD-10-CM rules."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

from app.rules import check_codes, parse_codes

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("CODER_MODEL", "icd-coder")
MODEL_VERSION = "codiesp-lora-v1-q8_0"     # recorded with every suggestion for the audit trail


class CodingEngine:
    def __init__(self, url=OLLAMA_URL, model=MODEL_NAME):
        self.url = url.rstrip("/")
        self.model = model
        self._check_ready()

    def _post(self, path, payload, timeout=300):
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _check_ready(self):
        """Fail early with a clear message if Ollama isn't running or the model isn't loaded."""
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=5) as resp:
                models = [m["name"] for m in json.loads(resp.read())["models"]]
        except urllib.error.URLError:
            raise RuntimeError(f"Ollama is not reachable at {self.url}. Is the Ollama app running?")
        if not any(m.split(":")[0] == self.model for m in models):
            raise RuntimeError(f"Model '{self.model}' not found in Ollama. Run: ollama create {self.model} -f Modelfile")

    def suggest(self, text):
        start = time.time()
        reply = self._post("/api/chat", {
            "model": self.model,
            "messages": [{"role": "user", "content": text}],   # the system prompt comes from the Modelfile
            "stream": False,
            "options": {"temperature": 0},
            "keep_alive": "30m",                               # keep the model in memory between requests
        })
        raw = reply["message"]["content"]
        result = check_codes(parse_codes(raw))
        result.update({
            "model_version": MODEL_VERSION,
            "raw_output": raw.strip(),
            "latency_seconds": round(time.time() - start, 2),
        })
        return result


if __name__ == "__main__":
    note = " ".join(sys.argv[1:]) or (
        "68-year-old male admitted for poorly controlled type 2 diabetes with hyperglycemia. "
        "History of hypertension. Persistent cough and headache for one week."
    )
    engine = CodingEngine()
    print(json.dumps(engine.suggest(note), indent=2))