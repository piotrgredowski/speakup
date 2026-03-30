import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

type ExtensionConfig = {
  enabled?: boolean;
  command?: string;
  args?: string[];
  onlyAssistant?: boolean;
  summaryMode?: "internal" | "agent_headless";
  headlessSummary?: {
    command?: string;
    args?: string[];
    model?: string;
    maxChars?: number;
    promptTemplate?: string;
  };
};

type ExecSpec = {
  command: string;
  args: string[];
  source: string;
};

const DEFAULT_CONFIG_PATH = join(homedir(), ".config", "let-me-know-agent", "pi-extension.json");

function loadConfig(ctx: any): Required<ExtensionConfig> {
  const defaults: Required<ExtensionConfig> = {
    enabled: true,
    command: "uvx",
    args: ["--from", "git+https://github.com/piotrgredowski/let-me-know-agent", "let-me-know-pi"],
    onlyAssistant: true,
    summaryMode: "internal",
    headlessSummary: {
      command: "pi",
      args: ["headless", "--model", "{model}", "--prompt", "{prompt}"],
      model: "default",
      maxChars: 220,
      promptTemplate:
        "Summarize this agent message for spoken notification in <= {maxChars} characters. Return only the summary text.\\n\\nEvent: {event}\\n\\nMessage:\\n{text}",
    },
  };

  if (!existsSync(DEFAULT_CONFIG_PATH)) return defaults;
  try {
    const raw = JSON.parse(readFileSync(DEFAULT_CONFIG_PATH, "utf8")) as ExtensionConfig;
    return {
      enabled: raw.enabled ?? defaults.enabled,
      command: raw.command ?? defaults.command,
      args: raw.args ?? defaults.args,
      onlyAssistant: raw.onlyAssistant ?? defaults.onlyAssistant,
      summaryMode: raw.summaryMode ?? defaults.summaryMode,
      headlessSummary: {
        command: raw.headlessSummary?.command ?? defaults.headlessSummary.command,
        args: raw.headlessSummary?.args ?? defaults.headlessSummary.args,
        model: raw.headlessSummary?.model ?? defaults.headlessSummary.model,
        maxChars: raw.headlessSummary?.maxChars ?? defaults.headlessSummary.maxChars,
        promptTemplate: raw.headlessSummary?.promptTemplate ?? defaults.headlessSummary.promptTemplate,
      },
    };
  } catch (err: any) {
    ctx.ui.notify(`let-me-know: invalid extension config: ${err?.message ?? err}`, "error");
    return defaults;
  }
}

function interpolateTemplate(template: string, values: Record<string, string | number>): string {
  let out = template;
  for (const [k, v] of Object.entries(values)) {
    out = out.split(`{${k}}`).join(String(v));
  }
  return out;
}

function summarizeWithHeadless(text: string, event: string, cfg: Required<ExtensionConfig>, ctx: any): Promise<string | null> {
  const h = cfg.headlessSummary;
  const prompt = interpolateTemplate(h.promptTemplate, {
    text,
    event,
    maxChars: h.maxChars,
  });

  const args = h.args.map((a) =>
    interpolateTemplate(a, {
      model: h.model,
      prompt,
      text,
      event,
      maxChars: h.maxChars,
    }),
  );

  return new Promise((resolve) => {
    const child = spawn(h.command, args, { stdio: ["ignore", "pipe", "pipe"] });

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));

    child.on("error", () => resolve(null));
    child.on("close", (code) => {
      if (code !== 0) {
        const detail = stderr.trim() || `exit code ${code}`;
        ctx.ui.notify(`let-me-know: headless summarizer failed (${detail}), falling back`, "warning");
        resolve(null);
        return;
      }
      const summary = stdout.trim();
      resolve(summary || null);
    });
  });
}

function extractText(message: any): string {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";

  const parts: string[] = [];
  for (const item of content) {
    if (typeof item === "string") parts.push(item);
    else if (item?.type === "text" && typeof item?.text === "string") parts.push(item.text);
  }
  return parts.join("\n").trim();
}

function runNotifier(command: string, args: string[], payload: Record<string, unknown>, ctx: any) {
  const configuredAsUvxBootstrap =
    command === "uvx" && args.includes("--from") && args.includes("let-me-know-pi");
  const fallbackCliArgs = configuredAsUvxBootstrap ? [] : args;

  const candidates: ExecSpec[] = [
    { command, args, source: "config" },
    {
      command: "uvx",
      args: ["--from", "git+https://github.com/piotrgredowski/let-me-know-agent", "let-me-know-pi", ...fallbackCliArgs],
      source: "uvx-git",
    },
    {
      command: "let-me-know-pi",
      args: fallbackCliArgs,
      source: "path-cli",
    },
    {
      command: "python3",
      args: ["-m", "let_me_know_agent.pi_command", ...fallbackCliArgs],
      source: "python3-module",
    },
    {
      command: "python",
      args: ["-m", "let_me_know_agent.pi_command", ...fallbackCliArgs],
      source: "python-module",
    },
  ];

  const dedupedCandidates: ExecSpec[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates) {
    const key = `${candidate.command}\u0000${candidate.args.join("\u0000")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    dedupedCandidates.push(candidate);
  }

  const tryIndex = (idx: number) => {
    if (idx >= dedupedCandidates.length) {
      ctx.ui.notify(
        "let-me-know: notifier unavailable. Install with `uv tool install let-me-know-agent` or `pip install let-me-know-agent`",
        "error",
      );
      return;
    }

    const spec = dedupedCandidates[idx];
    const child = spawn(spec.command, spec.args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));

    child.on("error", (err: any) => {
      if (err?.code === "ENOENT") {
        tryIndex(idx + 1);
        return;
      }
      ctx.ui.notify(`let-me-know: failed to start notifier: ${err?.message ?? err}`, "error");
    });

    child.on("close", (code) => {
      if (code === 0) return;

      const detail = stderr.trim() || stdout.trim() || `exit code ${code}`;

      // Backward-compatibility: older let-me-know-agent versions reject
      // summarization provider "command". Try the next candidate executable.
      if (
        detail.includes("summarization.provider_order contains unknown values") &&
        detail.includes("command") &&
        idx < dedupedCandidates.length - 1
      ) {
        ctx.ui.notify(
          `let-me-know: ${spec.source} is too old for provider 'command'; trying next fallback`,
          "warning",
        );
        tryIndex(idx + 1);
        return;
      }

      // If binary exists but failed (non-ENOENT), surface failure immediately.
      // For the default command only, we still try automatic fallbacks once.
      if (code === -2 && idx < dedupedCandidates.length - 1) {
        tryIndex(idx + 1);
        return;
      }

      ctx.ui.notify(`let-me-know: notifier failed via ${spec.source} (${detail})`, "error");
    });
  };

  tryIndex(0);
}

export default function (pi: ExtensionAPI) {
  let cfg: Required<ExtensionConfig> | undefined;

  const getCfg = (ctx: any): Required<ExtensionConfig> => {
    if (!cfg) cfg = loadConfig(ctx);
    return cfg;
  };

  pi.on("session_start", async (_event, ctx) => {
    cfg = loadConfig(ctx);
    if (cfg.enabled) {
      ctx.ui.notify("let-me-know extension active", "info");
    }
  });

  pi.on("message_end", async (event, ctx) => {
    const loadedCfg = getCfg(ctx);
    if (!loadedCfg.enabled) return;

    const role = event?.message?.role;
    if (loadedCfg.onlyAssistant && role !== "assistant") return;

    const text = extractText(event?.message);
    if (!text) return;

    const eventType = role === "assistant" ? "final" : "info";
    let summaryOverride: string | null = null;
    if (loadedCfg.summaryMode === "agent_headless") {
      summaryOverride = await summarizeWithHeadless(text, eventType, loadedCfg, ctx);
    }

    const payload = {
      message: text,
      event: eventType,
      ...(summaryOverride ? { summary: summaryOverride } : {}),
      agent: "pi",
      metadata: {
        source: "pi-message_end",
        role,
        ...(summaryOverride ? { summary_source: "agent_headless" } : {}),
      },
    };

    runNotifier(loadedCfg.command, loadedCfg.args, payload, ctx);
  });

  pi.registerCommand("letmeknow", {
    description: "Toggle let-me-know extension notifications (on/off/status)",
    handler: async (args, ctx) => {
      const loadedCfg = getCfg(ctx);
      const cmd = (args || "status").trim().toLowerCase();
      if (cmd === "on") {
        loadedCfg.enabled = true;
        ctx.ui.notify("let-me-know enabled", "info");
      } else if (cmd === "off") {
        loadedCfg.enabled = false;
        ctx.ui.notify("let-me-know disabled", "info");
      } else {
        ctx.ui.notify(`let-me-know is ${loadedCfg.enabled ? "enabled" : "disabled"}`, "info");
      }
    },
  });
}
