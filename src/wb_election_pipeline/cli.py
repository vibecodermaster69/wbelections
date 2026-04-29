from __future__ import annotations

import argparse
from pathlib import Path

from .coverage import missing_parsed_acs
from .data_quality import run_quality_checks
from .download import download_form20_pdfs, download_voter_roll_pdfs, get_voter_roll_parts
from .north_bengal import NORTH_BENGAL_ACS, build_booth_features, build_candidate_party_scaffold, build_scoped_candidate_votes
from .ocr import ocr_pdf_dir
from .parse_form20 import parse_gemini_markdown_dir, parse_llamacloud_markdown_dir, parse_pdf_dir
from .party import aggregate_party_shares
from .pdf_stream_inspect import inspect_pdf_streams
from .results_prefill import fetch_eci_candidate_results, prefill_candidate_party_map, resolve_candidate_party_map
from .simulate import run_monte_carlo
from .voter_roll_extract import parse_roll_count_markdown_dir, parse_roll_markdown_dir, parse_roll_summary_count_pdf_dir
from .voter_roll_match import compare_rolls


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-election")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download")
    download.add_argument("--out", type=Path, default=Path("data/raw/form20"))
    download.add_argument("--acs", type=int, nargs="*", default=NORTH_BENGAL_ACS,
                          help="AC numbers to download (default: North Bengal ACs 1-54)")
    download.add_argument("--all-acs", action="store_true",
                          help="Download all 294 WB ACs instead of North Bengal only")
    download.add_argument("--overwrite", action="store_true")
    download.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for legacy official sites")

    roll_parts = subparsers.add_parser("roll-parts")
    roll_parts.add_argument("--out", type=Path, default=Path("data/reference/north_bengal_2026_roll_parts.csv"))
    roll_parts.add_argument("--acs", type=int, nargs="*", default=NORTH_BENGAL_ACS,
                            help="AC numbers to inspect (default: North Bengal ACs 1-54)")
    roll_parts.add_argument("--all-acs", action="store_true")
    roll_parts.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for legacy official sites")

    download_rolls = subparsers.add_parser("download-rolls")
    download_rolls.add_argument("--out", type=Path, default=Path("data/rolls/2026/pdfs"))
    download_rolls.add_argument("--acs", type=int, nargs="*", default=NORTH_BENGAL_ACS,
                                help="AC numbers to download (default: North Bengal ACs 1-54)")
    download_rolls.add_argument("--all-acs", action="store_true")
    download_rolls.add_argument("--overwrite", action="store_true")
    download_rolls.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for legacy official sites")

    parse = subparsers.add_parser("parse")
    parse.add_argument("--pdf-dir", type=Path, default=Path("data/raw/form20"))
    parse.add_argument("--out", type=Path, default=Path("data/processed/wb_2021_form20_booth_candidate_votes.csv"))

    parse_llama = subparsers.add_parser("parse-llama-markdown")
    parse_llama.add_argument("--markdown-dir", type=Path, default=Path("data/ocr/llamacloud_markdown"))
    parse_llama.add_argument("--out", type=Path, default=Path("data/processed/wb_2021_form20_booth_candidate_votes.csv"))

    parse_gemini = subparsers.add_parser("parse-gemini-markdown")
    parse_gemini.add_argument("--markdown-dir", type=Path, default=Path("data/ocr_all/gemini_ocr_markdown"))
    parse_gemini.add_argument("--out", type=Path, default=Path("data/processed/wb_2021_form20_gemini_candidate_votes.csv"))

    missing = subparsers.add_parser("missing-acs")
    missing.add_argument("--pdf-dir", type=Path, default=Path("data/raw/form20"))
    missing.add_argument("--votes", type=Path, default=Path("data/processed/wb_2021_form20_native_candidate_votes.csv"))

    quality = subparsers.add_parser("quality")
    quality.add_argument("--votes", type=Path, default=Path("data/processed/wb_2021_form20_candidate_votes_best_source.csv"))
    quality.add_argument("--coverage", type=Path, default=Path("data/processed/wb_2021_form20_ac_coverage_best_source.csv"))
    quality.add_argument("--scope", type=Path)
    quality.add_argument("--ac-out", type=Path, default=Path("data/processed/wb_2021_form20_data_quality_summary.csv"))
    quality.add_argument("--booth-out", type=Path, default=Path("data/processed/wb_2021_form20_booth_quality_issues.csv"))

    roll_match = subparsers.add_parser("match-rolls")
    roll_match.add_argument("--old-roll", type=Path, required=True)
    roll_match.add_argument("--new-roll", type=Path, required=True)
    roll_match.add_argument("--scope", type=Path)
    roll_match.add_argument("--booth-out", type=Path, default=Path("data/processed/voter_roll_booth_retention.csv"))
    roll_match.add_argument("--ac-out", type=Path, default=Path("data/processed/voter_roll_ac_retention.csv"))

    parse_rolls = subparsers.add_parser("parse-roll-markdown")
    parse_rolls.add_argument("--markdown-dir", type=Path, required=True)
    parse_rolls.add_argument("--year", type=int, required=True)
    parse_rolls.add_argument("--out", type=Path, required=True)

    parse_roll_counts = subparsers.add_parser("parse-roll-counts")
    parse_roll_counts.add_argument("--markdown-dir", type=Path, required=True)
    parse_roll_counts.add_argument("--year", type=int, required=True)
    parse_roll_counts.add_argument("--out", type=Path, required=True)

    parse_roll_summary_counts = subparsers.add_parser("parse-roll-summary-counts")
    parse_roll_summary_counts.add_argument("--pdf-dir", type=Path, required=True)
    parse_roll_summary_counts.add_argument("--year", type=int, required=True)
    parse_roll_summary_counts.add_argument("--out", type=Path, required=True)
    parse_roll_summary_counts.add_argument("--recursive", action="store_true", help="Find PDFs recursively under --pdf-dir")
    parse_roll_summary_counts.add_argument(
        "--template-scan-limit",
        type=int,
        help="Only scan the first N PDFs while learning digit templates",
    )

    inspect_streams = subparsers.add_parser("inspect-pdf-streams")
    inspect_streams.add_argument("--pdf", type=Path, required=True)
    inspect_streams.add_argument("--out", type=Path)
    inspect_streams.add_argument("--stream-sample-limit", type=int, default=20)

    nb_clean = subparsers.add_parser("north-bengal-clean")
    nb_clean.add_argument("--votes", type=Path, default=Path("data/processed/wb_2021_form20_candidate_votes_best_source.csv"))
    nb_clean.add_argument("--quality", type=Path, default=Path("data/processed/north_bengal_form20_data_quality_summary.csv"))
    nb_clean.add_argument("--scope", type=Path, default=Path("data/reference/north_bengal_acs.csv"))
    nb_clean.add_argument("--out", type=Path, default=Path("data/processed/north_bengal_2021_booth_candidate_votes_clean.csv"))

    nb_party = subparsers.add_parser("north-bengal-party-scaffold")
    nb_party.add_argument("--votes", type=Path, default=Path("data/processed/north_bengal_2021_booth_candidate_votes_clean.csv"))
    nb_party.add_argument("--out", type=Path, default=Path("data/reference/north_bengal_candidate_party_map.csv"))

    nb_results = subparsers.add_parser("north-bengal-results-reference")
    nb_results.add_argument("--scope", type=Path, default=Path("data/reference/north_bengal_acs.csv"))
    nb_results.add_argument("--input-csv", type=Path, help="Official ECI candidate result CSV/XLSX to normalize if direct ECI fetch is blocked")
    nb_results.add_argument("--out", type=Path, default=Path("data/reference/north_bengal_2021_eci_candidate_results.csv"))

    nb_prefill = subparsers.add_parser("north-bengal-prefill-party-map")
    nb_prefill.add_argument("--scaffold", type=Path, default=Path("data/reference/north_bengal_candidate_party_map.csv"))
    nb_prefill.add_argument("--results", type=Path, default=Path("data/reference/north_bengal_2021_eci_candidate_results.csv"))
    nb_prefill.add_argument("--out", type=Path, default=Path("data/reference/north_bengal_candidate_party_map.csv"))
    nb_prefill.add_argument("--min-score", type=float, default=0.74)

    nb_resolve = subparsers.add_parser("north-bengal-resolve-party-map")
    nb_resolve.add_argument("--party-map", type=Path, default=Path("data/reference/north_bengal_candidate_party_map.csv"))
    nb_resolve.add_argument("--results", type=Path, default=Path("data/reference/north_bengal_2021_eci_candidate_results.csv"))
    nb_resolve.add_argument("--out", type=Path, default=Path("data/reference/north_bengal_candidate_party_map.csv"))
    nb_resolve.add_argument("--overrides", type=Path, default=Path("data/reference/north_bengal_candidate_party_overrides.csv"))
    nb_resolve.add_argument(
        "--unresolved-out",
        type=Path,
        default=Path("data/reference/north_bengal_candidate_party_map_priority_unmapped.csv"),
    )

    nb_features = subparsers.add_parser("north-bengal-features")
    nb_features.add_argument("--party-shares", type=Path, required=True)
    nb_features.add_argument("--roll-booth", type=Path)
    nb_features.add_argument("--turnout", type=Path)
    nb_features.add_argument("--scope", type=Path, default=Path("data/reference/north_bengal_acs.csv"))
    nb_features.add_argument("--out", type=Path, default=Path("data/processed/north_bengal_booth_model_features.csv"))

    ocr = subparsers.add_parser("ocr")
    ocr.add_argument("--pdf-dir", type=Path, default=Path("data/raw/form20"))
    ocr.add_argument("--out-dir", type=Path, default=Path("data/ocr_all"))
    ocr.add_argument("--providers", nargs="+", default=["glm_ocr"], choices=["llamacloud", "nutrient", "markitdown", "glm_ocr", "gemini_ocr"])
    ocr.add_argument("--language", default="english")
    ocr.add_argument("--overwrite", action="store_true")
    ocr.add_argument("--acs", type=int, nargs="*", default=NORTH_BENGAL_ACS,
                     help="AC numbers to OCR (default: North Bengal ACs 1-54)")
    ocr.add_argument("--all-acs", action="store_true",
                     help="OCR all ACs instead of North Bengal only")
    ocr.add_argument("--limit", type=int)
    ocr.add_argument("--recursive", action="store_true", help="Find PDFs recursively under --pdf-dir")

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--votes", type=Path, required=True)
    aggregate.add_argument("--party-map", type=Path, required=True)
    aggregate.add_argument("--out", type=Path, default=Path("data/processed/wb_2021_booth_party_shares.csv"))

    simulate = subparsers.add_parser("simulate")
    simulate.add_argument("--booth-shares", type=Path, required=True)
    simulate.add_argument("--out", type=Path, default=Path("data/processed/wb_2026_simulation_constituency_probabilities.csv"))
    simulate.add_argument("--iterations", type=int, default=10000)
    simulate.add_argument("--turnout-change", type=float, default=0.0)
    simulate.add_argument("--sir-deletion-factor", type=float, default=0.0)
    simulate.add_argument("--tmc-to-bjp-swing", type=float, default=0.0)
    simulate.add_argument("--noise-sd", type=float, default=0.015)
    simulate.add_argument("--ac-noise-sd", type=float, default=0.04)
    simulate.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    if args.command == "download":
        acs = None if args.all_acs else args.acs
        saved = download_form20_pdfs(args.out, acs, args.overwrite, verify_ssl=not args.insecure)
        print(f"Saved/found {len(saved)} PDFs in {args.out}")
    elif args.command == "roll-parts":
        acs = range(1, 295) if args.all_acs else args.acs
        rows = []
        for ac_no in acs:
            for part_no, booth_name in get_voter_roll_parts(ac_no, verify_ssl=not args.insecure):
                rows.append({"ac_no": ac_no, "part_no": part_no, "booth_name": booth_name})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        import pandas as pd

        pd.DataFrame(rows).to_csv(args.out, index=False)
        print(f"Wrote {len(rows)} roll part rows to {args.out}")
    elif args.command == "download-rolls":
        acs = None if args.all_acs else args.acs
        saved = download_voter_roll_pdfs(args.out, acs, args.overwrite, verify_ssl=not args.insecure)
        print(f"Saved/found {len(saved)} voter-roll PDFs in {args.out}")
    elif args.command == "parse":
        df = parse_pdf_dir(args.pdf_dir, args.out)
        print(f"Wrote {len(df)} booth-candidate rows to {args.out}")
    elif args.command == "parse-llama-markdown":
        df = parse_llamacloud_markdown_dir(args.markdown_dir, args.out)
        print(f"Wrote {len(df)} booth-candidate rows to {args.out}")
    elif args.command == "parse-gemini-markdown":
        df = parse_gemini_markdown_dir(args.markdown_dir, args.out)
        print(f"Wrote {len(df)} booth-candidate rows to {args.out}")
    elif args.command == "missing-acs":
        acs = missing_parsed_acs(args.pdf_dir, args.votes)
        print(" ".join(str(ac) for ac in acs))
    elif args.command == "quality":
        ac_quality, issues = run_quality_checks(
            args.votes,
            args.coverage,
            args.ac_out,
            args.booth_out,
            scope_csv=args.scope,
        )
        print(f"Wrote {len(ac_quality)} AC quality rows to {args.ac_out}")
        print(f"Wrote {len(issues)} booth issue rows to {args.booth_out}")
    elif args.command == "match-rolls":
        booth, ac = compare_rolls(
            args.old_roll,
            args.new_roll,
            args.booth_out,
            args.ac_out,
            scope_csv=args.scope,
        )
        print(f"Wrote {len(booth)} booth roll comparison rows to {args.booth_out}")
        print(f"Wrote {len(ac)} AC roll comparison rows to {args.ac_out}")
    elif args.command == "parse-roll-markdown":
        df = parse_roll_markdown_dir(args.markdown_dir, args.year, args.out)
        print(f"Wrote {len(df)} voter roll rows to {args.out}")
    elif args.command == "parse-roll-counts":
        df = parse_roll_count_markdown_dir(args.markdown_dir, args.year, args.out)
        print(f"Wrote {len(df)} voter roll count rows to {args.out}")
    elif args.command == "parse-roll-summary-counts":
        df = parse_roll_summary_count_pdf_dir(
            args.pdf_dir,
            args.year,
            args.out,
            recursive=args.recursive,
            template_scan_limit=args.template_scan_limit,
        )
        print(f"Wrote {len(df)} voter roll summary count rows to {args.out}")
    elif args.command == "inspect-pdf-streams":
        summary = inspect_pdf_streams(args.pdf, out_json=args.out, stream_sample_limit=args.stream_sample_limit)
        decoded = summary["aggregate_decoded"]
        text_operands = summary["aggregate_text_operands"]
        print(f"PDF: {summary['pdf']}")
        print(f"Pages: {summary['pages']}; streams: {summary['stream_count']}")
        print(
            "Decoded serial tokens: "
            f"{decoded['ascii_serial_token_count']} "
            f"({decoded['ascii_serial_unique_count']} unique, "
            f"min={decoded['ascii_serial_min']}, max={decoded['ascii_serial_max']})"
        )
        print(
            "Text-operand serial tokens: "
            f"{text_operands['ascii_serial_token_count']} "
            f"({text_operands['ascii_serial_unique_count']} unique, "
            f"min={text_operands['ascii_serial_min']}, max={text_operands['ascii_serial_max']})"
        )
        print(f"Markers: {summary['document_markers']}")
        if args.out:
            print(f"Wrote raw-stream summary to {args.out}")
    elif args.command == "north-bengal-clean":
        df = build_scoped_candidate_votes(args.votes, args.quality, args.scope, args.out)
        print(f"Wrote {len(df)} North Bengal candidate-vote rows to {args.out}")
    elif args.command == "north-bengal-party-scaffold":
        df = build_candidate_party_scaffold(args.votes, args.out)
        print(f"Wrote {len(df)} candidate-party scaffold rows to {args.out}")
    elif args.command == "north-bengal-results-reference":
        try:
            df = fetch_eci_candidate_results(args.out, scope_csv=args.scope, input_csv=args.input_csv)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Wrote {len(df)} North Bengal ECI candidate-result rows to {args.out}")
    elif args.command == "north-bengal-prefill-party-map":
        df = prefill_candidate_party_map(args.scaffold, args.results, args.out, min_score=args.min_score)
        filled = df["party"].fillna("").ne("").sum()
        print(f"Prefilled {filled} candidate-party rows in {args.out}")
    elif args.command == "north-bengal-resolve-party-map":
        before = 0
        if args.party_map.exists():
            import pandas as pd

            before = pd.read_csv(args.party_map)["party"].fillna("").ne("").sum()
        df = resolve_candidate_party_map(
            args.party_map,
            args.results,
            args.out,
            unresolved_out_csv=args.unresolved_out,
            overrides_csv=args.overrides,
        )
        filled = df["party"].fillna("").ne("").sum()
        print(f"Resolved {filled - before} additional candidate-party rows in {args.out}")
        print(f"Wrote unresolved priority rows to {args.unresolved_out}")
    elif args.command == "north-bengal-features":
        df = build_booth_features(args.party_shares, args.roll_booth, args.turnout, args.scope, args.out)
        print(f"Wrote {len(df)} North Bengal booth feature rows to {args.out}")
    elif args.command == "ocr":
        acs = None if args.all_acs else args.acs
        results, failures = ocr_pdf_dir(
            args.pdf_dir,
            args.out_dir,
            providers=args.providers,
            language=args.language,
            overwrite=args.overwrite,
            acs=acs,
            limit=args.limit,
            recursive=args.recursive,
        )
        if failures:
            failure_path = args.out_dir / "ocr_failures.csv"
            import pandas as pd

            pd.DataFrame(failures).to_csv(failure_path, index=False)
            print(f"OCR completed {len(results)} PDFs; {len(failures)} failed. See {failure_path}")
        else:
            print(f"OCR completed {len(results)} PDFs")
    elif args.command == "aggregate":
        df = aggregate_party_shares(args.votes, args.party_map, args.out)
        print(f"Wrote {len(df)} booth party-share rows to {args.out}")
    elif args.command == "simulate":
        df = run_monte_carlo(
            args.booth_shares,
            args.out,
            iterations=args.iterations,
            turnout_change=args.turnout_change,
            sir_deletion_factor=args.sir_deletion_factor,
            tmc_to_bjp_swing=args.tmc_to_bjp_swing,
            noise_sd=args.noise_sd,
            ac_noise_sd=args.ac_noise_sd,
            seed=args.seed,
        )
        print(f"Wrote {len(df)} constituency probability rows to {args.out}")


if __name__ == "__main__":
    main()
