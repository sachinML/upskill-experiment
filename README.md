# Gemini + Llama UPskill Setup

Minimal setup to generate and evaluate skills using **Gemini Pro as teacher**
and **Llama (via Ollama) as student**.

## Files


| File                             | Purpose                                                             |
| -------------------------------- | ------------------------------------------------------------------- |
| `patch.py`                       | Run once after installing upskill. fixes compatibility issues       |
| `refine.py`                      | Main script: generate, evaluate, and refine skill with custom tests |
| `tests.json`                     | Your custom test cases                                              |
| `instructions.txt`               | Task description for skill generation                               |
| `fastagent.config.yaml`          | FastAgent config: sets default model to Gemini Pro                  |
| `fastagent.secrets.yaml.example` | Template for API keys. copy to `fastagent.secrets.yaml`             |


## Requirements

- Python 3.13+
- [Ollama](https://ollama.com) (for local student model)
- Gemini API key (free at https://aistudio.google.com/apikey)
  
## Setup

### 1. Install dependencies

```bash
pip install upskill ollama
ollama pull llama3.2
```

### 2. Configure API keys

```bash
cp fastagent.secrets.yaml.example fastagent.secrets.yaml
```

Edit `fastagent.secrets.yaml` and add your Gemini API key

```yaml
google:
  api_key: YOUR_GEMINI_API_KEY

generic:
  base_url: "http://localhost:11434/v1"
  api_key: "ollama"
```

### 3. Apply compatibility patch (once)

```bash
python patch.py
```

This fixes four issues in the installed upskill package:

- Removes hardcoded Anthropic model from `test_gen.md`
- Strips `additionalProperties` from JSON schema (Gemini requirement)
- Removes evaluator line that corrupts `SKILL.md`
- Changes `TestCase extra="forbid"` to `extra="ignore"` (prevents silent failures)

### 4. Set up Ollama (student model)

```bash
# Pull the model you want to use as student
ollama pull llama3.2          # 3B: fast, lightweight

# Start the Ollama server (keep this running in a separate terminal)
ollama serve
```

**Model name format in commands:** `generic.<model-name>`

```bash
# Examples
--eval-model generic.llama3.2:latest
```

**Check available models:**

```bash
ollama list
```

**The `generic` provider** in `fastagent.secrets.yaml` tells FastAgent to use
any OpenAI-compatible endpoint. Ollama exposes one at `http://localhost:11434/v1`.

## Usage

```bash
TASK=$(cat instructions.txt)
python refine.py "$TASK" \
  --tests tests.json \
  --model google.gemini-2.5-pro \
  --eval-model generic.llama3.2:latest
```

### Options


| Option           | Default                 | Description                                     |
| ---------------- | ----------------------- | ----------------------------------------------- |
| `--tests`        | `tests.json`            | Your custom test cases file                     |
| `--model`        | `google.gemini-2.5-pro` | Teacher model (generates + evaluates + refines) |
| `--eval-model`   | none                    | Student model for final report                  |
| `--max-attempts` | `3`                     | Max refinement attempts                         |
| `--output`       | `./skills/<name>/`      | Where to save the skill                         |


## Test case format

```json
[
  {
    "input": "Clara is 29 and her email is clara@example.com",
    "expected": {
      "contains": ["Clara", "29", "clara@example.com"]
    }
  }
]
```

- `contains` is a list of strings that must ALL appear in the model output (case-insensitive)
- Keep checks **value-only** (not JSON key-value pairs) so they work across different model families

## Expected output

```
Loaded 35 custom test cases from tests.json
Teacher : google.gemini-2.5-pro  (generates, evaluates, refines)
Student : generic.llama3.2:latest  (final eval)
Attempts: up to 3

Generating skill with google.gemini-2.5-pro...
  Generated: extract-validate-user-info

  google.gemini-2.5-pro
    baseline   ███████░░░░░░░░░░░░░    37%
    with skill ██████████░░░░░░░░░░    51%  (+14%)

  generic.llama3.2:latest
    baseline   █████░░░░░░░░░░░░░░░    23%
    with skill ███████████████░░░░░    77%  (+54%)

Saved to ./skills/extract-validate-user-info
```

