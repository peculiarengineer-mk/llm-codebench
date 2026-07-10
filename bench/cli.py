"""Command-line entrypoint — the `llm-codebench` console script (T8).

Thin composition layer: parse args, build config, load problems, then drive the
runner and reporter. All heavy lifting lives in the modules it wires together.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from bench import config as cfg
from bench.openrouter import OpenRouterClient
from bench.problems import ProblemFormatError, load_problems
from bench.report import export_raw, render_cli, render_html
from bench.runner import dry_run_estimate, run_benchmark
from bench.sandbox import SandboxError, ensure_images
from bench.types import Language


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="llm-codebench",
        description="Benchmark LLM coding ability (Python/C#/TypeScript/Bash) plus "
        "speed and cost via OpenRouter, sandboxed in Docker.",
    )
    p.add_argument("--models", help="comma-separated OpenRouter model ids "
                   "(default: every id in config/models.yaml)")
    p.add_argument("--efforts", help="comma-separated reasoning-effort levels "
                   "(low,medium,high) to sweep every selected model across; "
                   "overrides per-entry 'efforts' in config/models.yaml")
    p.add_argument("--langs", help="comma-separated languages to run "
                   "(python,csharp,typescript,bash); default: all")
    p.add_argument("--k", type=int, help=f"attempts per problem (default {cfg.DEFAULT_K})")
    p.add_argument("--temp", type=float, help=f"sampling temperature "
                   f"(default {cfg.DEFAULT_TEMPERATURE})")
    p.add_argument("--timeout", type=float, help=f"per-attempt wall-clock seconds "
                   f"(default {cfg.DEFAULT_TIMEOUT})")
    p.add_argument("--max-spend", type=float, dest="max_spend",
                   help=f"USD spend cap for the run (default {cfg.DEFAULT_MAX_SPEND_USD})")
    p.add_argument("--max-tokens", type=int, dest="max_tokens",
                   help="cap completion tokens per request. Also bounds the credits "
                   "OpenRouter reserves up front, avoiding HTTP 402 on low-balance keys "
                   "(default: the model's own max, which can be very large)")
    p.add_argument("--dry-run", action="store_true",
                   help="price the run and exit before any paid API call")
    p.add_argument("--prompt-style", choices=["strict", "loose"],
                   help=f"prompt wrapper style (default {cfg.DEFAULT_PROMPT_STYLE})")
    p.add_argument("--problems", default="problems",
                   help="path to the problems/ tree (default: ./problems)")
    p.add_argument("--filter", help="only run problems whose slug contains this substring")
    p.add_argument("--out", default="results",
                   help="output directory for HTML + raw exports (default: results/)")
    p.add_argument("--concurrency", type=int, default=4,
                   help="max in-flight API calls (default 4)")
    return p


def _parse_langs(raw: str | None) -> list[Language] | None:
    if not raw:
        return None
    langs: list[Language] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            langs.append(Language(token))
        except ValueError:
            valid = ", ".join(x.value for x in Language)
            raise SystemExit(f"error: unknown language {token!r} (valid: {valid})")
    return langs


def _print_estimate(estimate, config, console) -> None:
    from rich.table import Table

    table = Table(title=f"Dry run — cost estimate (k={config.k})", title_style="bold")
    table.add_column("Model", style="cyan")
    table.add_column("calls", justify="right")
    table.add_column("~prompt tok", justify="right")
    table.add_column("~compl tok", justify="right")
    table.add_column("~cost", justify="right")
    for m in estimate.per_model:
        cost = "unpriced" if not m.priced else f"${m.est_cost_usd:.4f}"
        table.add_row(m.model, str(m.calls), f"{m.est_prompt_tokens:,}",
                      f"{m.est_completion_tokens:,}", cost)
    console.print(table)
    console.print(
        f"\nTotal: [bold]{estimate.total_calls}[/bold] calls, "
        f"est. [bold]${estimate.total_cost_usd:.4f}[/bold] "
        f"(cap ${config.max_spend_usd:.2f})"
    )
    if estimate.has_unpriced:
        console.print("[yellow]Some models had no known pricing; their cost is "
                      "estimated as $0. Set price_override in config/models.yaml.[/yellow]")
    if estimate.total_cost_usd > config.max_spend_usd:
        console.print("[red]Estimated cost exceeds --max-spend; the run would be "
                      "halted by the spend guard before completing.[/red]")


async def _amain(args: argparse.Namespace) -> int:
    from rich.console import Console

    console = Console()

    # -- config + problems --------------------------------------------------
    specs = cfg.load_model_specs()
    price_overrides = {s.id: s.price_override for s in specs if s.price_override is not None}
    models = [m.strip() for m in args.models.split(",")] if args.models else None
    efforts = (
        [e.strip() for e in args.efforts.split(",") if e.strip()]
        if args.efforts
        else None
    )
    langs = _parse_langs(args.langs)

    try:
        run_config = cfg.build_run_config(
            models=models,
            efforts=efforts,
            k=args.k,
            temperature=args.temp,
            timeout=args.timeout,
            max_spend_usd=args.max_spend,
            max_tokens=args.max_tokens,
            dry_run=args.dry_run,
            prompt_style=args.prompt_style,
        )
    except ValueError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        return 2

    try:
        problems = load_problems(args.problems, langs, args.filter)
    except ProblemFormatError as exc:
        console.print(f"[red]Problem loading failed:[/red] {exc}")
        return 2
    if not problems:
        console.print(f"[red]No problems found under {args.problems!r}[/red] "
                      "(expected problems/<lang>/<slug>/ directories).")
        return 2

    console.print(f"Loaded [bold]{len(problems)}[/bold] problems across "
                  f"[bold]{len(run_config.models)}[/bold] models.")

    # -- API key ------------------------------------------------------------
    try:
        api_key = cfg.get_api_key()
    except RuntimeError as exc:
        if args.dry_run and price_overrides:
            api_key = None  # can still price from overrides
        else:
            console.print(f"[red]{exc}[/red]")
            return 2

    referer = __import__("os").environ.get("OPENROUTER_HTTP_REFERER")
    title = __import__("os").environ.get("OPENROUTER_X_TITLE")

    async with OpenRouterClient(
        api_key or "",
        price_overrides=price_overrides,
        referer=referer,
        title=title,
    ) as client:
        # -- dry run --------------------------------------------------------
        if run_config.dry_run:
            pricing = {}
            if api_key:
                try:
                    pricing = await client.get_pricing()
                except Exception as exc:  # noqa: BLE001 — best-effort pricing
                    console.print(f"[yellow]Could not fetch live pricing: {exc}[/yellow]")
            for model, price in price_overrides.items():
                from bench.openrouter import ModelPricing
                pricing[model] = ModelPricing(price, price, "config")
            estimate = dry_run_estimate(run_config, problems, pricing)
            _print_estimate(estimate, run_config, console)
            return 0

        # -- real run: sandbox images then benchmark ------------------------
        needed = sorted({p.language for p in problems}, key=lambda x: x.value)
        try:
            console.print("Ensuring sandbox images (first run builds them)…")
            await ensure_images(needed)
        except SandboxError as exc:
            console.print(f"[red]Sandbox unavailable:[/red] {exc}")
            return 3

        console.print("Running benchmark…")
        result = await run_benchmark(
            run_config, problems, client, concurrency=args.concurrency
        )

    # -- report -------------------------------------------------------------
    if result.aborted_reason:
        console.print(f"\n[red bold]{result.aborted_reason}[/red bold]")
        console.print("[yellow]Tip: pass --max-tokens to shrink the up-front credit "
                      "reservation, or top up the key. Results below are partial.[/yellow]\n")
    render_cli(result)
    out_dir = Path(args.out)
    json_path, csv_path = export_raw(result, out_dir)
    html_path = render_html(result, out_dir / "report.html")
    Console().print(
        f"\nWrote [green]{html_path}[/green], [green]{json_path}[/green], "
        f"[green]{csv_path}[/green]"
    )
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_amain(args)))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
