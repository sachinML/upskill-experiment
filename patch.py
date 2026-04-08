import importlib.util
import sys
from pathlib import Path

GEMINI_MODEL = "google.gemini-2.5-pro"
PATCH_MARKER = "# [gemini-patch]"

NEW_LINES = f"""\
{PATCH_MARKER} — strip additionalProperties for Gemini structured output compatibility
from typing import Any as _Any


def _strip_additional_properties(schema: dict[str, _Any]) -> None:
    \"\"\"Recursively remove additionalProperties from a JSON schema in-place.\"\"\"
    schema.pop("additionalProperties", None)
    for value in schema.values():
        if isinstance(value, dict):
            _strip_additional_properties(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_additional_properties(item)

"""

TEST_CASE_SUITE_PATCH = f"""\
    @classmethod
    def model_json_schema(cls, **kwargs: _Any) -> dict[str, _Any]:  {PATCH_MARKER}
        schema: dict[str, _Any] = super().model_json_schema(**kwargs)
        _strip_additional_properties(schema)
        return schema
"""


def find_package_dir() -> Path:
    spec = importlib.util.find_spec("upskill.models")
    if spec is None or spec.origin is None:
        print("ERROR: upskill is not installed.")
        print("  Run: pip install upskill")
        sys.exit(1)
    return Path(spec.origin).parent


# Fix 1: agent card

def patch_agent_cards(package_dir: Path) -> None:
    """Replace hardcoded Anthropic model in test_gen.md with Gemini."""
    card_path = package_dir / "agent_cards" / "test_gen.md"
    if not card_path.exists():
        print(f"WARNING: Agent card not found at {card_path} — skipping.")
        return

    content = card_path.read_text(encoding="utf-8")

    if PATCH_MARKER in content:
        print(f"Agent card already patched: {card_path}")
        return

    # Replace any hardcoded model line (e.g. 'model: opus?reasoning=1024')
    lines = content.splitlines(keepends=True)
    new_lines = []
    patched = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model:") and not stripped.startswith("#"):
            new_lines.append(f"model: {GEMINI_MODEL}  {PATCH_MARKER}\n")
            patched = True
        else:
            new_lines.append(line)

    if not patched:
        # No model line existed, insert one after the opening ---
        result = []
        in_frontmatter = False
        inserted = False
        for line in new_lines:
            result.append(line)
            if line.strip() == "---" and not inserted:
                if not in_frontmatter:
                    in_frontmatter = True
                else:
                    result.insert(-1, f"model: {GEMINI_MODEL}  {PATCH_MARKER}\n")
                    inserted = True
        new_lines = result

    card_path.write_text("".join(new_lines), encoding="utf-8")
    print(f"Patched agent card: {card_path}")


# Fix 2: JSON schema

def patch_models_file(package_dir: Path) -> None:
    """Strip additionalProperties from TestCaseSuite JSON schema."""
    path = package_dir / "models.py"
    if not path.exists():
        print(f"ERROR: models.py not found at {path}")
        sys.exit(1)

    original = path.read_text(encoding="utf-8")

    if PATCH_MARKER in original or "_strip_additional_properties" in original:
        print(f"models.py already patched: {path}")
        return

    insert_before = "\nclass SkillMetadata"
    if insert_before not in original:
        print("ERROR: Could not find insertion point in models.py.")
        print("  The upskill version may have changed. Please open an issue.")
        sys.exit(1)

    patched = original.replace(insert_before, f"\n{NEW_LINES}class SkillMetadata", 1)

    suite_marker = "    cases: list[TestCase] = Field(default_factory=list)"
    if suite_marker not in patched:
        print("ERROR: Could not find TestCaseSuite.cases field in models.py.")
        sys.exit(1)

    patched = patched.replace(
        suite_marker,
        f"{suite_marker}\n\n{TEST_CASE_SUITE_PATCH}",
        1,
    )

    backup = path.with_suffix(".py.bak")
    backup.write_text(original, encoding="utf-8")
    print(f"Backup saved:       {backup}")
    path.write_text(patched, encoding="utf-8")
    print(f"Patched models.py:  {path}")


# Fix 4: TestCase extra="forbid" → extra="ignore"

def patch_testcase_extra(package_dir: Path) -> None:
    """Change TestCase.model_config extra='forbid' to extra='ignore'.

    Claude (and other non-Anthropic models) may return extra fields like
    "description" alongside "input"/"expected". With extra="forbid" Pydantic
    raises ValidationError, which FastAgent catches silently and returns None,
    producing "Test generator did not return structured test cases."
    Switching to extra="ignore" drops unknown fields rather than failing.
    """
    path = package_dir / "models.py"
    if not path.exists():
        print(f"ERROR: models.py not found at {path}")
        sys.exit(1)

    content = path.read_text(encoding="utf-8")

    # Target the TestCase class block specifically
    old_snippet = (
        'class TestCase(BaseModel):\n'
        '    """A test case for skill evaluation."""\n'
        '\n'
        '    model_config = ConfigDict(extra="forbid")'
    )
    new_snippet = (
        'class TestCase(BaseModel):\n'
        '    """A test case for skill evaluation."""\n'
        '\n'
        f'    model_config = ConfigDict(extra="ignore")  {PATCH_MARKER}'
    )

    if f'model_config = ConfigDict(extra="ignore")  {PATCH_MARKER}' in content:
        print(f"TestCase.extra already patched: {path}")
        return

    if old_snippet not in content:
        print("WARNING: Could not find TestCase model_config in models.py — skipping Fix 4.")
        print("  (The upskill version may differ; extra fields from Claude will cause silent failures.)")
        return

    patched = content.replace(old_snippet, new_snippet, 1)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched TestCase.extra in models.py: {path}")


# Fix 3: evaluator agent card

def patch_evaluator_card(package_dir: Path) -> None:
    """Remove skills: ["./skills"] from evaluator.md to prevent SKILL.md corruption."""
    card_path = package_dir / "agent_cards" / "evaluator.md"
    if not card_path.exists():
        print(f"WARNING: evaluator.md not found at {card_path} — skipping.")
        return

    content = card_path.read_text(encoding="utf-8")

    if 'skills: ["./skills"]' not in content:
        print(f"evaluator.md already patched: {card_path}")
        return

    patched = content.replace(
        'skills: ["./skills"]',
        f'# skills: ["./skills"]  {PATCH_MARKER} removed — was overwriting SKILL.md with model output',
    )
    # Also remove {{agentSkills}} template since skills are no longer loaded
    patched = patched.replace("\n{{agentSkills}}", "")

    card_path.write_text(patched, encoding="utf-8")
    print(f"Patched evaluator.md: {card_path}")



if __name__ == "__main__":
    package_dir = find_package_dir()
    print(f"Found upskill package at: {package_dir}")
    print()
    patch_agent_cards(package_dir)
    patch_models_file(package_dir)
    patch_testcase_extra(package_dir)
    patch_evaluator_card(package_dir)
    print()
    print("Done. upskill is now compatible with Google Gemini.")
