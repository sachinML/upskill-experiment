# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  refine.py: upskill generate with custom test cases                         │
# │                                                                             │
# │  ORIGIN OF EACH SECTION:                                                    │
# │  [COPIED]: taken directly from upskill/cli.py _generate_async()             │
# │  [MODIFIED]:copied from upskill/cli.py but changed                          │
# │  [NEW]: written from scratch, not in original upskill                       │
# └─────────────────────────────────────────────────────────────────────────────┘

import asyncio
import json
from pathlib import Path

import click
from rich.console import Console

from upskill.cli import _fast_agent_context, _save_and_display
from upskill.config import Config
from upskill.evaluate import evaluate_skill, get_failure_descriptions
from upskill.generate import generate_skill, refine_skill
from upskill.logging import (
    aggregate_conversation_stats,
    create_batch_folder,
    create_run_folder,
    write_batch_summary,
    write_run_metadata,
    write_run_result,
)
from upskill.models import BatchSummary, RunMetadata, RunResult, TestCase

console = Console()


async def _run(
    task: str,
    tests_file: str,
    model: str | None,
    eval_model: str | None,
    max_attempts: int,
    output: str | None,
) -> None:
    # [COPIED] load config and resolve models
    config = Config.load()
    gen_model = model or config.model or "google.gemini-2.5-pro"
    student_model = eval_model or config.eval_model or None

    # ── [NEW] Load custom test cases from file
    # Original upskill calls: test_cases = await generate_tests(task, generator=agent.test_gen, model=model)
    # We replace that with loading from a user-provided JSON file.
    tests_path = Path(tests_file)
    if not tests_path.exists():
        console.print(f"[red]Tests file not found: {tests_file}[/red]")
        raise SystemExit(1)

    raw = json.loads(tests_path.read_text())
    cases_raw = raw.get("cases", raw) if isinstance(raw, dict) else raw
    test_cases = [TestCase.model_validate(tc) for tc in cases_raw]

    # [NEW] Summary banner showing teacher/student/attempt config
    console.print(f"Loaded [bold]{len(test_cases)}[/bold] custom test cases from {tests_file}")
    console.print(f"Teacher : [bold]{gen_model}[/bold]  (generates, evaluates, refines)")
    if student_model:
        console.print(f"Student : [bold]{student_model}[/bold]  (final eval)")
    console.print(f"Attempts: up to {max_attempts}\n")

    # [COPIED] run logging setup
    attempts = max(1, max_attempts)
    runs_path = config.runs_dir
    batch_id, batch_folder = create_batch_folder(runs_path)
    run_results: list[RunResult] = []
    console.print(f"Logging runs to: {batch_folder}", style="dim")

    async with _fast_agent_context() as agent:

        # ── Step 1: Generate skill

        # [NEW] Explicitly set the model on the agent before calling generate_skill().
        # In original upskill CLI, model= is passed to generate_skill() but that only
        # sets metadata, it does NOT change the agent's actual model. This line fixes that.
        await agent.skill_gen.set_model(gen_model)

        # [COPIED] skill generation call
        console.print(f"\nGenerating skill with {gen_model}...", style="dim")
        skill = await generate_skill(
            task=task,
            generator=agent.skill_gen,
            model=gen_model,
        )
        console.print(f"  Generated: [bold]{skill.name}[/bold]")

        # ── Step 2: Teacher eval + refine loop
        # [COPIED] entire loop body from upskill/cli.py lines 343–439
        # The only difference: test_cases comes from our file, not generate_tests()
        prev_success_rate = 0.0
        results = None

        for attempt in range(attempts):
            console.print(f"\nEvaluating on {gen_model}... (attempt {attempt + 1})", style="dim")

            baseline_run_num = attempt * 2 + 1
            run_folder = create_run_folder(batch_folder, baseline_run_num)
            write_run_metadata(run_folder, RunMetadata(
                model=gen_model, task=task,
                batch_id=batch_id, run_number=baseline_run_num,
            ))

            console.print("[dim]Starting evaluation run...[/dim]")
            results = await evaluate_skill(
                skill,
                test_cases=test_cases,      # [MODIFIED] was auto generated, now from file
                evaluator=agent.evaluator,
                model=gen_model,
            )

            # [COPIED] log baseline result
            baseline_result = RunResult(
                metadata=RunMetadata(model=gen_model, task=task,
                                     batch_id=batch_id, run_number=baseline_run_num),
                stats=aggregate_conversation_stats(results.baseline_results),
                passed=results.baseline_success_rate > 0.5,
                assertions_passed=int(results.baseline_success_rate * len(test_cases)),
                assertions_total=len(test_cases),
                run_type="baseline",
                skill_name=skill.name,
            )
            write_run_result(run_folder, baseline_result)
            run_results.append(baseline_result)

            # [COPIED] log with-skill result
            with_skill_folder = create_run_folder(batch_folder, attempt * 2 + 2)
            with_skill_result = RunResult(
                metadata=RunMetadata(model=gen_model, task=task,
                                     batch_id=batch_id, run_number=attempt * 2 + 2),
                stats=aggregate_conversation_stats(results.with_skill_results),
                passed=results.is_beneficial,
                assertions_passed=int(results.with_skill_success_rate * len(test_cases)),
                assertions_total=len(test_cases),
                run_type="with_skill",
                skill_name=skill.name,
            )
            write_run_metadata(with_skill_folder, with_skill_result.metadata)
            write_run_result(with_skill_folder, with_skill_result)
            run_results.append(with_skill_result)

            # [COPIED] early stop if skill is beneficial (any positive lift)
            lift = results.skill_lift
            lift_str = f"+{lift:.0%}" if lift > 0 else f"{lift:.0%}"

            if results.is_beneficial:
                console.print(
                    f"  {results.baseline_success_rate:.0%} -> "
                    f"{results.with_skill_success_rate:.0%} ({lift_str}) [green]OK[/green]"
                )
                break

            console.print(
                f"  {results.baseline_success_rate:.0%} -> "
                f"{results.with_skill_success_rate:.0%} ({lift_str}) not good enough"
            )

            # [COPIED] plateau check: stop if improvement < 5%
            if abs(results.with_skill_success_rate - prev_success_rate) < 0.05:
                console.print("  [yellow]Plateaued, stopping[/yellow]")
                break

            prev_success_rate = results.with_skill_success_rate

            # [COPIED] refine skill based on failures
            if attempt < attempts - 1:
                console.print("Refining...", style="dim")
                failures = get_failure_descriptions(results)
                skill = await refine_skill(
                    skill, failures,
                    generator=agent.skill_gen,
                    model=gen_model,
                )

        # ── Step 3: Student eval (final report)
        # [COPIED] from upskill/cli.py lines 441–513
        # Runs only if --eval-model is provided
        eval_results = None
        if student_model:
            console.print(f"\nEvaluating on {student_model}...", style="dim")

            run_number = attempts * 2 + 1
            run_folder = create_run_folder(batch_folder, run_number)
            write_run_metadata(run_folder, RunMetadata(
                model=student_model, task=task,
                batch_id=batch_id, run_number=run_number,
            ))

            eval_results = await evaluate_skill(
                skill,
                test_cases=test_cases,      # [MODIFIED] was auto-generated, now from file
                evaluator=agent.evaluator,
                model=student_model,
            )

            # [COPIED] log student baseline + with-skill results
            baseline_result = RunResult(
                metadata=RunMetadata(model=student_model, task=task,
                                     batch_id=batch_id, run_number=run_number),
                stats=aggregate_conversation_stats(eval_results.baseline_results),
                passed=eval_results.baseline_success_rate > 0.5,
                assertions_passed=int(eval_results.baseline_success_rate * len(test_cases)),
                assertions_total=len(test_cases),
                run_type="baseline",
                skill_name=skill.name,
            )
            write_run_result(run_folder, baseline_result)
            run_results.append(baseline_result)

            with_skill_folder = create_run_folder(batch_folder, run_number + 1)
            with_skill_result = RunResult(
                metadata=RunMetadata(model=student_model, task=task,
                                     batch_id=batch_id, run_number=run_number + 1),
                stats=aggregate_conversation_stats(eval_results.with_skill_results),
                passed=eval_results.is_beneficial,
                assertions_passed=int(eval_results.with_skill_success_rate * len(test_cases)),
                assertions_total=len(test_cases),
                run_type="with_skill",
                skill_name=skill.name,
            )
            write_run_metadata(with_skill_folder, with_skill_result.metadata)
            write_run_result(with_skill_folder, with_skill_result)
            run_results.append(with_skill_result)

            lift = eval_results.skill_lift
            lift_str = f"+{lift:.0%}" if lift > 0 else f"{lift:.0%}"
            console.print(
                f"  {eval_results.baseline_success_rate:.0%} -> "
                f"{eval_results.with_skill_success_rate:.0%} ({lift_str})"
            )

        # ── Step 4: Save + display
        # [COPIED] batch summary + _save_and_display (identical to upskill generate)
        write_batch_summary(batch_folder, BatchSummary(
            batch_id=batch_id, model=gen_model, task=task,
            total_runs=len(run_results),
            passed_runs=sum(1 for r in run_results if r.passed),
            results=run_results,
        ))

        if results:
            skill.metadata.test_pass_rate = results.with_skill_success_rate

        _save_and_display(skill, output, config, results, eval_results, gen_model, student_model)


# [NEW] CLI wrapper: original upskill uses a much more complex click command
# with --from-trace, --from-skill, --no-eval, --examples etc. that we don't need.
# We expose only the options relevant to custom-test-driven generation.
@click.command()
@click.argument("task")
@click.option(
    "--tests", "-t", "tests_file",
    default="tests.json", show_default=True,
    help="JSON file with your custom test cases",
)
@click.option(
    "--model", "-m",
    default=None,
    help="Teacher model: generates, evaluates, and refines the skill",
)
@click.option(
    "--eval-model", "-e",
    default=None,
    help="Student model: final evaluation only (optional)",
)
@click.option(
    "--max-attempts", "-n",
    default=3, show_default=True,
    help="Max teacher refinement attempts",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output directory for the skill (default: ./skills/<skill-name>/)",
)
def main(task, tests_file, model, eval_model, max_attempts, output):
    """
    upskill generate — but with YOUR test cases instead of auto-generated ones.

    Teacher evaluates and refines the skill. Student (if given) runs a final
    report. Same output format as upskill generate.
    """
    asyncio.run(_run(task, tests_file, model, eval_model, max_attempts, output))


if __name__ == "__main__":
    main()
