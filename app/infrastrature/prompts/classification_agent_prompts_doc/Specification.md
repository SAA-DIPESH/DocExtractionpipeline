# Specification — Document Classification Agent

## Purpose

Classify a single tender document into one of the allowed document types using the supplied document metadata and classification taxonomy.

The agent must not generate or modify document metadata.
Its only responsibility is to identify the most appropriate document type.

--------------------------------------------------

## Required Input

```json
{
  "document_metadata": {
    "file_name": "",
    "file_stem": "",
    "document_title": "",
    "summary": "",
    "main_headings": [],
    "section_titles": [],
    "keywords": [],
    "top_ngrams": [],
    "named_entities": [],
    "table_headers": [],
    "table_count": 0,
    "image_count": 0,
    "page_count": 0,
    "processing_status": "SUCCESS"
  },

  "classification_set": [
    {
      "code": "",
      "name": "",
      "expectedSignals": []
    }
  ]
}
```

--------------------------------------------------

## Processing Steps

1. Read the supplied document metadata.

2. Read the supplied classification taxonomy.

3. Analyse the following evidence:

   - document_title
   - summary
   - main_headings
   - section_titles
   - keywords
   - top_ngrams
   - named_entities
   - table_headers

4. Compare the document evidence against each taxonomy item's expectedSignals.

5. Select the single best matching document type.

6. Assign an appropriate numeric confidence score.

7. Produce a short explanation describing why the selected document type was chosen.

--------------------------------------------------

## Classification Rules

- Use ONLY the supplied classification_set.

- Never invent new document types.

- Never modify the supplied taxonomy.

- Base the classification only on the supplied document metadata.

- Prefer the taxonomy entry with the strongest evidence match.

- If multiple document types are similar, choose the one with the highest evidence overlap.

- If there is insufficient evidence to classify the document, return:

```
UNKNOWN_OR_UNCLEAR
```

--------------------------------------------------

## Confidence Score Rules

90-100
- Very strong evidence from title, headings and summary.
- Multiple expectedSignals are matched with little ambiguity.

70-89
- Strong evidence from title, headings or summary.
- Several expectedSignals are matched.

40-69
- Partial evidence.
- Some expectedSignals are matched, but ambiguity remains.

0-39
- Weak evidence.
- Only a few expectedSignals are matched.
- Use 0 when there is insufficient evidence to classify the document.

--------------------------------------------------

## Generated JSON Contract

```json
{
  "document_type": "",
  "classification_confidence": 0,
  "reason": ""
}
```

--------------------------------------------------

## Validation Rules

- document_type must come only from the supplied classification_set.

- classification_confidence must be a number from 0 to 100.

- classification_confidence must not be a string label such as HIGH, MEDIUM or LOW.

- reason must be concise (maximum two sentences).

- Do not invent document types.

- Do not generate additional metadata.

- Return valid JSON only.
