import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

type ExecResult = {
  exitCode: number;
  stdout: string;
  stderr: string;
};

const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = resolve(EXTENSION_DIR, "..");
const SRC_ROOT = resolve(PACKAGE_ROOT, "src");
const DEFAULT_PROJECT_ROOT_ENV = "PI_LEAN_TOOLS_PROJECT_ROOT";
const DEFAULT_PROBE_TIMEOUT_SEC = 60;

function execFileText(
  command: string,
  args: string[],
  options: { cwd: string; signal?: AbortSignal; timeoutMs?: number },
): Promise<ExecResult> {
  return new Promise((resolvePromise) => {
    const env = {
      ...process.env,
      PYTHONPATH: process.env.PYTHONPATH ? `${SRC_ROOT}:${process.env.PYTHONPATH}` : SRC_ROOT,
    };
    const child = execFile(
      command,
      args,
      {
        cwd: options.cwd,
        env,
        signal: options.signal,
        timeout: options.timeoutMs ?? 60_000,
        maxBuffer: 1024 * 1024 * 8,
      },
      (error, stdout, stderr) => {
        const anyError = error as NodeJS.ErrnoException | null;
        resolvePromise({
          exitCode:
            typeof (anyError as any)?.code === "number"
              ? ((anyError as any).code as number)
              : anyError
                ? 1
                : 0,
          stdout: String(stdout ?? ""),
          stderr: String(stderr ?? ""),
        });
      },
    );
    options.signal?.addEventListener("abort", () => {
      child.kill("SIGTERM");
    });
  });
}

function truncateText(text: string, maxChars = 12_000): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n\n[truncated ${text.length - maxChars} chars]`;
}

function parseJsonOrFailure(tool: string, stdout: string, stderr: string): Record<string, unknown> {
  try {
    return JSON.parse(stdout) as Record<string, unknown>;
  } catch (error) {
    return {
      tool,
      status: "runner_failed",
      data: {
        error: error instanceof Error ? error.message : String(error),
        stdout: truncateText(stdout),
        stderr: truncateText(stderr),
      },
      diagnostics: [
        {
          severity: "error",
          message: "pi-lean-tools CLI did not return valid JSON",
          file: null,
          line: null,
          column: null,
        },
      ],
      authority: {
        usable_as_context: true,
        usable_as_proof_evidence: false,
        proof_authority: "none",
        advisory_only: true,
      },
      final_verify_required: true,
    };
  }
}

function formatJson(value: unknown): string {
  return truncateText(JSON.stringify(value, null, 2));
}

async function runCli(
  tool: string,
  args: string[],
  cwd: string,
  signal?: AbortSignal,
  timeoutMs = 60_000,
) {
  const result = await execFileText(
    "python3",
    ["-m", "pi_lean_tools.cli", ...args],
    { cwd, signal, timeoutMs },
  );
  const payload = parseJsonOrFailure(tool, result.stdout, result.stderr);
  if (result.exitCode !== 0) {
    payload.status = "runner_failed";
    payload.data = {
      ...((payload.data as Record<string, unknown>) ?? {}),
      exitCode: result.exitCode,
      stderr: truncateText(result.stderr),
    };
  }
  return {
    content: [{ type: "text" as const, text: formatJson(payload) }],
    details: payload,
  };
}

function projectArgs(projectRoot: string | undefined, ctxCwd: string): string[] {
  const configuredRoot = projectRoot ?? process.env[DEFAULT_PROJECT_ROOT_ENV] ?? ".";
  return ["--project-root", resolve(ctxCwd, configuredRoot)];
}

function importArgs(imports: string[] | undefined): string[] {
  const values = imports && imports.length > 0 ? imports : ["Mathlib"];
  return values.flatMap((item) => ["--imports", item]);
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "lean_scout_check_names",
    label: "Lean Scout Check Names",
    description:
      "Run #check probes for candidate Lean declaration names in a Lake project. Use for uncertain Mathlib names, names suggested by search, and names involved in Unknown constant/identifier errors. Advisory context only; not proof authority.",
    promptSnippet:
      "Use lean_scout_check_names before relying on Lean declaration names you are not sure exist.",
    promptGuidelines: [
      "Use lean_scout_check_names when you are about to write or reuse a theorem/definition name from memory.",
      "Use lean_scout_check_names before reusing names that caused Unknown constant or unknown identifier errors.",
      "Use lean_scout_check_names after lean_scout_decl_search to confirm exact names and theorem shapes.",
      "lean_scout_check_names uncertainty can be recorded in worker_report.json under needed_external_checks kind=api_name.",
      "lean_scout_check_names uses PI_LEAN_TOOLS_PROJECT_ROOT when projectRoot is omitted and the runner configured it.",
      "lean_scout_check_names #check success is context only, not proof evidence.",
      "lean_scout_check_names does not replace FinalVerify for formal closure.",
    ],
    parameters: Type.Object({
      names: Type.Array(Type.String()),
      projectRoot: Type.Optional(Type.String()),
      imports: Type.Optional(Type.Array(Type.String())),
      timeoutSec: Type.Optional(Type.Number()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = [
        "check-names",
        ...projectArgs(params.projectRoot, ctx.cwd),
        ...importArgs(params.imports),
        "--timeout-sec",
        String(params.timeoutSec ?? DEFAULT_PROBE_TIMEOUT_SEC),
        ...params.names,
      ];
      const timeoutSec = params.timeoutSec ?? DEFAULT_PROBE_TIMEOUT_SEC;
      return runCli("lean_scout_check_names", args, ctx.cwd, signal, timeoutSec * 1000 + 10_000);
    },
  });

  pi.registerTool({
    name: "lean_scout_check_snippet",
    label: "Lean Scout Check Snippet",
    description:
      "Elaborate a small Lean snippet in a Lake project. Use for focused API/type-shape probes before committing larger Lean proof edits. Returns elaboration diagnostics only; not proof authority.",
    promptSnippet:
      "Use lean_scout_check_snippet for small Lean API probes before writing larger API-dependent proof code.",
    promptGuidelines: [
      "Use lean_scout_check_snippet for coercions, gcd/coprime APIs, finite set APIs, divisibility rewrites, type mismatch repair, or tactic-local theorem shape checks.",
      "Use lean_scout_check_snippet when a current frontier is blocked on a small API/type-shape question instead of guessing inside a large candidate edit.",
      "lean_scout_check_snippet probes can be recorded in worker_report.json under needed_external_checks kind=snippet.",
      "lean_scout_check_snippet uses PI_LEAN_TOOLS_PROJECT_ROOT when projectRoot is omitted and the runner configured it.",
      "lean_scout_check_snippet status=elaborated is API/context evidence only, not proof verification.",
      "lean_scout_check_snippet does not replace FinalVerify.",
      "Keep lean_scout_check_snippet code small and targeted.",
    ],
    parameters: Type.Object({
      code: Type.String(),
      projectRoot: Type.Optional(Type.String()),
      imports: Type.Optional(Type.Array(Type.String())),
      timeoutSec: Type.Optional(Type.Number()),
      allowSorry: Type.Optional(Type.Boolean()),
      mode: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = [
        "check-snippet",
        ...projectArgs(params.projectRoot, ctx.cwd),
        ...importArgs(params.imports),
        "--timeout-sec",
        String(params.timeoutSec ?? DEFAULT_PROBE_TIMEOUT_SEC),
        "--mode",
        params.mode ?? "api_probe",
        params.allowSorry === false ? "--no-allow-sorry" : "--allow-sorry",
        "--code",
        params.code,
      ];
      const timeoutSec = params.timeoutSec ?? DEFAULT_PROBE_TIMEOUT_SEC;
      return runCli("lean_scout_check_snippet", args, ctx.cwd, signal, timeoutSec * 1000 + 10_000);
    },
  });

  pi.registerTool({
    name: "lean_scout_decl_search",
    label: "Lean Scout Declaration Search",
    description:
      "Search local project and local Mathlib source declarations by name or statement tokens. Use when you know keywords or a mathematical role but not the exact Lean declaration name. Advisory context only.",
    promptSnippet:
      "Use lean_scout_decl_search instead of guessing Mathlib names from memory.",
    promptGuidelines: [
      "Use lean_scout_decl_search for Unknown constant, uncertain namespace, theorem-family lookup, or a proof step that needs a known Mathlib lemma.",
      "Use lean_scout_decl_search before turning an uncertain theorem-family guess into candidate Lean code.",
      "lean_scout_decl_search results can be recorded in worker_report.json under needed_external_checks kind=api_name.",
      "lean_scout_decl_search uses PI_LEAN_TOOLS_PROJECT_ROOT when projectRoot is omitted and the runner configured it.",
      "lean_scout_decl_search results are not verified names until checked with lean_scout_check_names.",
      "Use lean_scout_decl_search recommended_check snippets to confirm exact names.",
      "lean_scout_decl_search results do not select a unique proof route.",
    ],
    parameters: Type.Object({
      query: Type.String(),
      projectRoot: Type.Optional(Type.String()),
      limit: Type.Optional(Type.Number()),
      includeMathlib: Type.Optional(Type.Boolean()),
      includeLocal: Type.Optional(Type.Boolean()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = [
        "decl-search",
        ...projectArgs(params.projectRoot, ctx.cwd),
        "--query",
        params.query,
        "--limit",
        String(params.limit ?? 20),
      ];
      if (params.includeMathlib === false) args.push("--no-mathlib");
      if (params.includeLocal === false) args.push("--no-local");
      return runCli("lean_scout_decl_search", args, ctx.cwd, signal);
    },
  });

  pi.registerTool({
    name: "lean_scout_error_explain",
    label: "Lean Scout Error Explain",
    description:
      "Classify a Lean diagnostic and return concrete next scout actions. Use immediately after Unknown constant, unknown identifier, failed rewrite, type mismatch, or suspicious Mathlib API failure. Advisory context only.",
    promptSnippet:
      "Use lean_scout_error_explain to turn Lean errors into concrete check/search probes.",
    promptGuidelines: [
      "Use lean_scout_error_explain when the previous checker feedback includes a named Lean diagnostic.",
      "Use lean_scout_error_explain when checker feedback is concrete enough to quote; it is the fastest scout entry after compile_failed.",
      "lean_scout_error_explain diagnostics that remain unresolved can be summarized in worker_report.json as needed_external_checks.",
      "Use lean_scout_error_explain suggested_actions as next probes, not as proof instructions.",
      "After lean_scout_error_explain returns do_not_repeat_exact_name, do not repeat those exact names unless imports or mathlib revision changed.",
      "When lean_scout_error_explain classifies a missing name, check the normalized name or search nearby theorem families.",
    ],
    parameters: Type.Object({
      errorMessage: Type.String(),
      surroundingCode: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["error-explain", "--error-message", params.errorMessage];
      if (params.surroundingCode) args.push("--surrounding-code", params.surroundingCode);
      return runCli("lean_scout_error_explain", args, ctx.cwd, signal);
    },
  });

  pi.registerTool({
    name: "lean_scout_premise_search",
    label: "Lean Scout Premise Search",
    description:
      "Build advisory route-local premise groups from local Lean declarations. Use when a proof task likely needs several related premises rather than one exact theorem. Search results are context only.",
    promptSnippet:
      "Use lean_scout_premise_search when you know the proof role but need a premise bundle.",
    promptGuidelines: [
      "Use lean_scout_premise_search for finite image, injectivity, gcd/coprime, divisibility, parity, absolute value, or descent premise roles.",
      "Use lean_scout_premise_search when you can describe the proof role but do not yet know the local Mathlib premise family.",
      "lean_scout_premise_search needs can be recorded in worker_report.json under needed_external_checks kind=premise_search.",
      "lean_scout_premise_search uses PI_LEAN_TOOLS_PROJECT_ROOT when projectRoot is omitted and the runner configured it.",
      "lean_scout_premise_search returns premise groups as a toolbox, not a selected proof route.",
      "Names returned by lean_scout_premise_search are not verified until checked with lean_scout_check_names.",
      "Use lean_scout_premise_search groups to decide focused scout probes before editing candidate code.",
    ],
    parameters: Type.Object({
      naturalLanguageGoal: Type.String(),
      projectRoot: Type.Optional(Type.String()),
      leanContext: Type.Optional(Type.String()),
      queryTerms: Type.Optional(Type.Array(Type.String())),
      routes: Type.Optional(Type.Array(Type.String())),
      limitPerGroup: Type.Optional(Type.Number()),
      includeMathlib: Type.Optional(Type.Boolean()),
      includeLocal: Type.Optional(Type.Boolean()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = [
        "premise-search",
        ...projectArgs(params.projectRoot, ctx.cwd),
        "--natural-language-goal",
        params.naturalLanguageGoal,
        "--limit-per-group",
        String(params.limitPerGroup ?? 5),
      ];
      if (params.leanContext) args.push("--lean-context", params.leanContext);
      for (const term of params.queryTerms ?? []) args.push("--query-term", term);
      for (const route of params.routes ?? []) args.push("--route", route);
      if (params.includeMathlib === false) args.push("--no-mathlib");
      if (params.includeLocal === false) args.push("--no-local");
      return runCli("lean_scout_premise_search", args, ctx.cwd, signal);
    },
  });

  pi.registerTool({
    name: "lean_scout_try_tactics",
    label: "Lean Scout Try Tactics",
    description:
      "Run a closing-tactic portfolio (exact?, simp, omega, norm_num, ...) against one Lean goal declaration. exact?/apply? suggestions report the exact lemma closing the goal, so this doubles as premise search. Advisory probe only; not proof authority.",
    promptSnippet:
      "Use lean_scout_try_tactics on a focused subgoal before hand-writing a proof for it.",
    promptGuidelines: [
      "Use lean_scout_try_tactics with a self-contained declaration header like 'example (h : 0 < n) : n ≠ 0', without ':= by ...'.",
      "Use lean_scout_try_tactics on extracted sorry subgoals to learn which standard tactic or lemma closes them.",
      "Read the suggestions field: 'Try this: exact <lemma> ...' names the exact Mathlib premise to reuse.",
      "lean_scout_try_tactics outcomes are advisory probe evidence only; the full candidate must still pass FinalVerify.",
      "Do not submit tactics forbidden by the theorem contract even if they close the probe goal.",
      "lean_scout_try_tactics uses PI_LEAN_TOOLS_PROJECT_ROOT when projectRoot is omitted and the runner configured it.",
    ],
    parameters: Type.Object({
      goalDeclaration: Type.String(),
      projectRoot: Type.Optional(Type.String()),
      imports: Type.Optional(Type.Array(Type.String())),
      tactics: Type.Optional(Type.Array(Type.String())),
      timeoutSec: Type.Optional(Type.Number()),
      stopAfterFirstClose: Type.Optional(Type.Boolean()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const timeoutSec = params.timeoutSec ?? DEFAULT_PROBE_TIMEOUT_SEC;
      const args = [
        "try-tactics",
        ...projectArgs(params.projectRoot, ctx.cwd),
        ...importArgs(params.imports),
        "--timeout-sec",
        String(timeoutSec),
        "--goal",
        params.goalDeclaration,
      ];
      for (const tactic of params.tactics ?? []) args.push("--tactic", tactic);
      if (params.stopAfterFirstClose) args.push("--stop-after-first-close");
      const tacticCount = (params.tactics ?? []).length || 10;
      return runCli("lean_scout_try_tactics", args, ctx.cwd, signal, timeoutSec * tacticCount * 1000 + 10_000);
    },
  });
}
