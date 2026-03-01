# Prompt Changelog

All LLM prompts are in `nasvetlo/prompts/`. Track changes here.

## v1.0.0 (Initial MVP)

### coherence_validator.txt
- Initial version. Requires strict JSON output.
- Distinguishes "same event" from "same topic".

### source_summary_json.txt
- Initial version. Extracts key_facts, uncertainties, entities, numbers_dates.

### article_writer.txt
- Initial version. Bulgarian language. 700-900 words.
- Structure: title, lead, body, context, sources.
- Prohibits fabrication, accusatory language, clickbait.

### self_edit.txt
- Initial version. 8-point checklist.
- Returns revised article + checklist + changes.

### safety_classifier_json.txt
- Initial version. Three risk levels (low/medium/high).
- Checks for defamation, unattributed accusations, sensitive claims.

### seo_fields_json.txt
- Initial version. Generates title, description, slug, tags, category.
- Category options: политика, икономика, общество, свят, технологии, спорт, култура.
