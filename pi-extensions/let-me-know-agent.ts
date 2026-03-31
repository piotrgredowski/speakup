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
};

const DEFAULT_CONFIG_PATH = join(homedir(), ".config", "let-me-know-agent", "pi-extension.json");

function loadConfig(ctx: any): Required<ExtensionConfig> {
  const defaults: Required<ExtensionConfig> = {
    enabled: true,
    command: "let-me-know",
    args: ["pi"],
    onlyAssistant: true,
  };

  if (!existsSync(DEFAULT_CONFIG_PATH)) return defaults;

  try {
    const raw = JSON.parse(readFileSync(DEFAULT_CONFIG_PATH, "utf8")) as ExtensionConfig;
    return {
      enabled: raw.enabled ?? defaults.enabled,
      command: raw.command ?? defaults.command,
      args: raw.args ?? defaults.args,
      onlyAssistant: raw.onlyAssistant ?? defaults.onlyAssistant,
    };
  } catch (err: any) {
    ctx.ui.notify(`let-me-know: invalid extension config: ${err?.message ?? err}`, "error");
    return defaults;
  }
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
  const child = spawn(command, args, {
    stdio: ["pipe", "pipe", "pipe"],
  });

  child.stdin.write(JSON.stringify(payload));
  child.stdin.end();

  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (d) => (stdout += d.toString()));
  child.stderr.on("data", (d) => (stderr += d.toString()));

  child.on("error", (err: any) => {
    ctx.ui.notify(`let-me-know: failed to start notifier: ${err?.message ?? err}`, "error");
  });

  child.on("close", (code) => {
    if (code === 0) return;
    const detail = stderr.trim() || stdout.trim() || `exit code ${code}`;
    ctx.ui.notify(`let-me-know: notifier failed (${detail})`, "error");
  });
}

export default function (pi: ExtensionAPI) {
  let config: Required<ExtensionConfig> | undefined;

  const getConfig = (ctx: any): Required<ExtensionConfig> => {
    if (!config) config = loadConfig(ctx);
    return config;
  };

  pi.on("session_start", async (_event, ctx) => {
    config = loadConfig(ctx);
    if (config.enabled) {
      ctx.ui.notify("let-me-know extension active", "info");
    }
  });

  pi.on("message_end", async (event, ctx) => {
    const cfg = getConfig(ctx);
    if (!cfg.enabled) return;

    const role = event?.message?.role;
    if (cfg.onlyAssistant && role !== "assistant") return;

    const text = extractText(event?.message);
    if (!text) return;

    const eventType = role === "assistant" ? "final" : "info";
    const payload = {
      message: text,
      event: eventType,
      agent: "pi",
      metadata: {
        source: "pi-message_end",
        role,
      },
    };

    runNotifier(cfg.command, cfg.args, payload, ctx);
  });

  pi.registerCommand("letmeknow", {
    description: "Toggle let-me-know extension notifications (on/off/status)",
    handler: async (args, ctx) => {
      const cfg = getConfig(ctx);
      const cmd = (args || "status").trim().toLowerCase();

      if (cmd === "on") {
        cfg.enabled = true;
        ctx.ui.notify("let-me-know enabled", "info");
      } else if (cmd === "off") {
        cfg.enabled = false;
        ctx.ui.notify("let-me-know disabled", "info");
      } else {
        ctx.ui.notify(`let-me-know is ${cfg.enabled ? "enabled" : "disabled"}`, "info");
      }
    },
  });
}
