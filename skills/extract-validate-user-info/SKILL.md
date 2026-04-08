---
name: extract-validate-user-info
description: Extract and validate name, age, and email from unstructured text into a strict JSON format.
---

# Extract and Validate User Information

## Overview

This skill teaches how to parse unstructured text to extract specific user details: name, age, and email. The objective is to return this information in a strictly-defined JSON format, ensuring all data is validated according to specific rules and that missing or invalid fields are represented as `null`.

## Key Principles & Rules

1.  **Strict Schema:** The output must *only* be a JSON object with the exact keys: `"name"`, `"age"`, and `"email"`.
2.  **Handle Missing Data:** If a piece of information is not found or is invalid, its value in the JSON must be `null`.
3.  **No Hallucination:** Do not invent or infer data. If it's not explicitly present in the text, it must be `null`.
4.  **Age Validation:** An age must be a numeric integer. Textual representations ("thirty"), ranges ("in his 40s"), or ambiguity must result in `null`. Look for contextual keywords like "age" or "years old".
5.  **Email Validation:** An email must conform to a standard `user@domain.tld` format. Use a reliable regular expression for validation.

## Example Implementation (Python)

This example uses regular expressions to find and validate the required information before constructing the final JSON output.

```python
import re
import json

def extract_user_info(text: str) -> str:
    """
    Extracts and validates name, age, and email from text and returns a JSON string.
    """
    # 1. Email Extraction & Validation
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email_match = re.search(email_pattern, text)
    email = email_match.group(0) if email_match else None

    # 2. Age Extraction & Validation (must be digits)
    # Looks for a number explicitly labeled with age-related keywords.
    age_pattern = r'\b(\d{1,3})\s*(?:years old|yrs old|yo)\b|\bage is (\d{1,3})\b'
    age_match = re.search(age_pattern, text, re.IGNORECASE)
    age = None
    if age_match:
        age_val = age_match.group(1) or age_match.group(2)
        if age_val:
            age = int(age_val)

    # 3. Name Extraction (simple pattern-based approach)
    # Looks for common introductory phrases. More advanced NLP can be used.
    name_pattern = r'(?:my name is|I am|I\'m)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'
    name_match = re.search(name_pattern, text, re.IGNORECASE)
    name = name_match.group(1).strip() if name_match else None

    # Construct the final JSON object
    result = {
        "name": name,
        "age": age,
        "email": email
    }

    # Return only the JSON string
    return json.dumps(result)
```

## Scenarios and Expected Outputs

| Input Text                                                 | Expected JSON Output (as a raw string)                        |
| ---------------------------------------------------------- | ------------------------------------------------------------- |
| "Hi, I'm Jane Doe. I am 32 years old. jane.d@example.com"   | `{"name": "Jane Doe", "age": 32, "email": "jane.d@example.com"}` |
| "John's email is john@work.co.uk. He is in his forties."    | `{"name": null, "age": null, "email": "john@work.co.uk"}`       |
| "My name is Bob. My age is twenty five."                    | `{"name": "Bob", "age": null, "email": null}`                  |
| "The user ID is 42, and the contact is admin@site.org."     | `{"name": null, "age": null, "email": "admin@site.org"}`       |
| "Contact me at not-a-valid-email@com"                       | `{"name": null, "age": null, "email": null}`                   |

## Best Practices & Pitfalls

-   **Be Conservative:** Name extraction is notoriously difficult. If a name isn't clearly identified with a phrase like "My name is...", it is safer to return `null` than to misidentify a common noun.
-   **Context is Crucial:** Do not just find any number and assume it's an age. The regex should look for contextual keywords like "age" or "years old" to avoid errors.
-   **Final Output Format:** The final response must be **only** the raw JSON string. Do not wrap it in markdown code fences (```json) or add any explanatory text.
-   **Use `null`, not `"null"`:** Ensure that null values in the final JSON are the JSON `null` literal, not a string containing the word "null". Standard JSON libraries (like Python's `json`) handle this correctly when the Python value is `None`.