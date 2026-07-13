from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

BASE_DIR = Path(__file__).resolve().parent / "classification_agent_prompts_doc"

CONSTITUTION = (
    BASE_DIR
    / "Constitution.md"
).read_text(encoding="utf-8")

SPECIFICATION = (
    BASE_DIR
    / "Specification.md"
).read_text(encoding="utf-8")

SYSTEM_PROMPT = (
    BASE_DIR
    / "system_prompt.md"
).read_text(encoding="utf-8")


DOCUMENT_INTELLIGENCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
==================================================
SYSTEM PROMPT
==================================================

{system_prompt}

==================================================
CONSTITUTION
==================================================

{constitution}

==================================================
SPECIFICATION
==================================================

{specification}

==================================================
GENERAL INSTRUCTIONS
==================================================

You MUST follow the System Prompt, Constitution and Specification exactly.

The Constitution defines:
- Behaviour
- Guardrails
- Quality standards

The Specification defines:
- Required input
- Processing workflow
- Output schema
- Validation rules

Return exactly one valid JSON object.

Do not return Markdown.

Do not explain your reasoning.

Do not omit required fields.

Do not invent information.

If information cannot be extracted from the document,
return null, an empty list, or UNKNOWN as defined in the Specification.
"""
        ),
        (
            "human",
            """
========================
DOCUMENT INPUT
========================

Document Name:
{document_name}

Page Count:
{page_count}

Table Count:
{table_count}

Classification Taxonomy:
{classification_set}

========================
DOCUMENT CONTENT
========================

{document_text}

Analyse the document according to the Constitution and Specification.

Return ONLY the required JSON object.
"""
        ),
    ]
).partial(
    constitution=CONSTITUTION,
    specification=SPECIFICATION,
    system_prompt=SYSTEM_PROMPT,
)
