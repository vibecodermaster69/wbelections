# West Bengal Election Pipeline

Python pipeline for:

1. Downloading official West Bengal 2021 Assembly Form 20 PDFs.
2. Parsing booth-wise candidate votes from Form 20 tables.
3. Normalizing candidate party labels into BJP/TMC/other buckets.
4. Exporting clean booth-level CSVs for modeling.
5. Running a booth-level Monte Carlo model with turnout, SIR deletion, and swing assumptions.

Official Form 20 source pattern:

```text
https://ceowestbengal.wb.gov.in/Downloads/Election/GE2021/Form20/{ac_no}_Form20.pdf
```

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

## Download Form 20 PDFs

Download all 294 Assembly Constituency PDFs:

```powershell
wb-election download --out data/raw/form20
```

Download a subset:

```powershell
wb-election download --acs 129 145 261 --out data/raw/form20
```

If the official site fails with a legacy TLS or certificate-chain error on your Python install, use:

```powershell
wb-election download --acs 129 --out data/raw/form20 --insecure
```

## Parse Booth Votes

```powershell
wb-election parse --pdf-dir data/raw/form20 --out data/processed/wb_2021_form20_booth_candidate_votes.csv
```

Some CEO PDFs are scanned/image-only. For those, the parser writes a sibling
`*.failures.csv` explaining which files need OCR or manual review instead of
silently returning bad data.

The parser emits one row per booth-candidate:

```text
ac_no, ac_name, total_electors, polling_station, candidate, votes, source_pdf
```

## Add Party Mapping

Form 20 PDFs usually list candidate names, not party names. Create a candidate-party map:

```powershell
Copy-Item data/reference/candidate_party_map.sample.csv data/reference/candidate_party_map.csv
```

Fill `party` for each `ac_no,candidate`. Then aggregate BJP/TMC booth shares:

```powershell
wb-election aggregate `
  --votes data/processed/wb_2021_form20_booth_candidate_votes.csv `
  --party-map data/reference/candidate_party_map.csv `
  --out data/processed/wb_2021_booth_party_shares.csv
```

## Monte Carlo Simulation

Example:

```powershell
wb-election simulate `
  --booth-shares data/processed/wb_2021_booth_party_shares.csv `
  --turnout-change 0.02 `
  --sir-deletion-factor 0.01 `
  --tmc-to-bjp-swing 0.015 `
  --iterations 10000 `
  --out data/processed/wb_2026_simulation_constituency_probabilities.csv
```

Parameters:

- `turnout-change`: proportional change in booth total votes, e.g. `0.02` means +2%.
- `sir-deletion-factor`: proportional reduction in booth votes before turnout/swing, e.g. `0.01` means -1%.
- `tmc-to-bjp-swing`: vote-share swing from TMC to BJP. Negative values swing BJP to TMC.
- `noise-sd`: booth-level normal noise standard deviation applied to two-party share.

The simulation reports constituency-level BJP/TMC mean votes and win probabilities.

## North Bengal Workflow

Build the scoped Form 20 candidate-vote file:

```powershell
wb-election north-bengal-clean
```

Create the candidate-party review scaffold:

```powershell
wb-election north-bengal-party-scaffold
```

Create an official ECI candidate-party reference and prefill the scaffold:

```powershell
wb-election north-bengal-results-reference
wb-election north-bengal-prefill-party-map
```

If ECI blocks automated downloads, export/download the official ECI candidate
result table as CSV/XLSX and normalize it instead:

```powershell
wb-election north-bengal-results-reference `
  --input-csv data/reference/eci_wb_2021_candidate_results.xlsx `
  --out data/reference/north_bengal_2021_eci_candidate_results.csv
```

Review unresolved rows in `data/reference/north_bengal_candidate_party_map.csv`,
then aggregate booth party shares:

```powershell
wb-election north-bengal-resolve-party-map
```

This resolver only fills guarded same-AC matches from the official ECI candidate
list plus entries from `data/reference/north_bengal_candidate_party_overrides.csv`.
It leaves ambiguous fragments in
`data/reference/north_bengal_candidate_party_map_priority_unmapped.csv`.

```powershell
wb-election aggregate `
  --votes data/processed/north_bengal_2021_booth_candidate_votes_clean.csv `
  --party-map data/reference/north_bengal_candidate_party_map.csv `
  --out data/processed/north_bengal_2021_booth_party_shares.csv
```

Parse extracted voter-roll markdown into the required roll schema:

```powershell
wb-election parse-roll-markdown --markdown-dir data/rolls/2021/markdown --year 2021 --out data/processed/north_bengal_roll_2021.csv
wb-election parse-roll-markdown --markdown-dir data/rolls/2026/markdown --year 2026 --out data/processed/north_bengal_roll_2026.csv
```

For 2026 final-roll PDFs from the CEO West Bengal endpoint, first create a
parts manifest and then download the PDFs:

```powershell
wb-election roll-parts --out data/reference/north_bengal_2026_roll_parts.csv --insecure
wb-election download-rolls --out data/rolls/2026/pdfs --insecure
```

For the counts-only modeling path, OCR the downloaded PDFs and extract one
registered-voter count per AC/part:

```powershell
$env:GEMINI_OCR_TASK="voter_roll"
wb-election ocr `
  --pdf-dir data/rolls/2026/pdfs `
  --out-dir data/rolls/2026/ocr `
  --providers gemini_ocr `
  --recursive

wb-election parse-roll-counts `
  --markdown-dir data/rolls/2026/ocr/gemini_ocr_markdown `
  --year 2026 `
  --out data/processed/north_bengal_2026_roll_booth_counts.csv

wb-election north-bengal-features `
  --party-shares data/processed/north_bengal_2021_booth_party_shares.csv `
  --roll-booth data/processed/north_bengal_2026_roll_booth_counts.csv `
  --out data/processed/north_bengal_booth_model_features.csv
```

Compare 2021 and 2026 rolls:

```powershell
wb-election match-rolls `
  --old-roll data/processed/north_bengal_roll_2021.csv `
  --new-roll data/processed/north_bengal_roll_2026.csv `
  --scope data/reference/north_bengal_acs.csv `
  --booth-out data/processed/north_bengal_roll_booth_retention.csv `
  --ac-out data/processed/north_bengal_roll_ac_retention.csv
```

Build joined booth model features after party shares and roll retention are available:

```powershell
wb-election north-bengal-features `
  --party-shares data/processed/north_bengal_2021_booth_party_shares.csv `
  --roll-booth data/processed/north_bengal_roll_booth_retention.csv `
  --turnout data/reference/north_bengal_turnout_template.csv `
  --out data/processed/north_bengal_booth_model_features.csv
```

## OCR Fallbacks

For scanned Form 20 PDFs, configure `.env` with one or more rotating keys:

```text
LLAMA_CLOUD_API_KEY_1=...
LLAMA_CLOUD_API_KEY_2=...
NUTRIENT_API_KEY=...
NUTRIENT_ACCESSIBILITY_KEY=...
GEMINI_API_KEY_1=...
GEMINI_API_KEY_2=...
GEMINI_OCR_MODEL=gemini-2.5-flash-lite
```

Run OCR before parsing:

```powershell
wb-election ocr --pdf-dir data/raw/form20 --out-dir data/ocr --providers llamacloud nutrient
```

Provider behavior:

- LlamaCloud saves Markdown to `data/ocr/llamacloud_markdown`.
- Nutrient saves searchable PDFs to `data/ocr/nutrient_searchable_pdfs` and extracted text to `data/ocr/nutrient_text`.
- MarkItDown saves Markdown to `data/ocr/markitdown_markdown`.
- Gemini saves Markdown to `data/ocr/gemini_ocr_markdown`; set `GEMINI_OCR_TASK=voter_roll` before OCR for Bengali electoral roll PDFs.
- Keys are tried in order by environment variable name. Logs store only key names, never secret values.
- MarkItDown base conversion works without a key for text-layer PDFs. Scanned PDF OCR requires `OPENAI_API_KEY` so the `markitdown-ocr` plugin can call a vision model. Set `MARKITDOWN_LLM_MODEL` to override the default `gpt-4o`.
- If Nutrient creates searchable PDFs, parse those with:

```powershell
wb-election parse --pdf-dir data/ocr/nutrient_searchable_pdfs --out data/processed/wb_2021_form20_booth_candidate_votes.csv
```

- If Gemini creates voter-roll Markdown, parse it with:

```powershell
$env:GEMINI_OCR_TASK="voter_roll"
wb-election ocr --pdf-dir data/rolls/2026/pdfs --out-dir data/rolls/2026/ocr --providers gemini_ocr
wb-election parse-roll-markdown --markdown-dir data/rolls/2026/ocr/gemini_ocr_markdown --year 2026 --out data/processed/north_bengal_roll_2026.csv
```

- If LlamaCloud creates Markdown tables, parse those with:

```powershell
wb-election parse-llama-markdown --markdown-dir data/ocr/llamacloud_markdown --out data/processed/wb_2021_form20_booth_candidate_votes.csv
```

- If MarkItDown creates Markdown tables, try the same markdown parser:

```powershell
wb-election parse-llama-markdown --markdown-dir data/ocr/markitdown_markdown --out data/processed/wb_2021_form20_markitdown_candidate_votes.csv
```

## Important Limits

This pipeline can estimate booth-level party behavior from official counting data, but it cannot identify individual voters or who a specific person voted for. Indian ballots are secret; booth-level Form 20 data is aggregate only.
