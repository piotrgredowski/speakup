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

const DEFAULT_CONFIG_PATH = join(homedir(), ".config", "speakup", "pi-extension.json");

function loadConfig(ctx: any): Required<ExtensionConfig> {
  const defaults: Required<ExtensionConfig> = {
    enabled: true,
    command: "speakup",
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
    ctx.ui.notify(`speakup: invalid extension config: ${err?.message ?? err}`, "error");
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

function extractSessionKey(event: any): string {
  const candidates = [
    event?.sessionKey,
    event?.conversationId,
    event?.sessionId,
    event?.session?.id,
    event?.session?.sessionId,
    event?.message?.sessionKey,
    event?.message?.conversationId,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function getVersion(command: string, ctx: any): void {
  const child = spawn(command, ["--version"], {
    stdio: ["pipe", "pipe", "pipe"],
  });

  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (d) => (stdout += d.toString()));
  child.stderr.on("data", (d) => (stderr += d.toString()));

  child.on("error", () => {
    ctx.ui.notify(`speakup: version check failed`, "info");
  });

  child.on("close", (code) => {
    if (code === 0 && stdout.trim()) {
      ctx.ui.notify(`speakup: version ${stdout.trim()}`, "info");
    }
  });
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
    ctx.ui.notify(`speakup: failed to start notifier: ${err?.message ?? err}`, "error");
  });

  child.on("close", (code) => {
    if (code === 0) return;
    const detail = stderr.trim() || stdout.trim() || `exit code ${code}`;
    ctx.ui.notify(`speakup: notifier failed (${detail})`, "error");
  });
}

function buildReplayCommandArgs(cfg: Required<ExtensionConfig>, count: string, sessionKey: string): string[] {
  const baseArgs = [...cfg.args];

  for (let i = 0; i < baseArgs.length; i += 1) {
    if (baseArgs[i] === "speakup-pi") {
      baseArgs[i] = "speakup";
      break;
    }
  }

  const piIndex = baseArgs.findIndex((value) => value === "pi");
  if (piIndex >= 0) {
    baseArgs.splice(piIndex, 1);
  }

  return [...baseArgs, "replay", count, "--agent", "pi", "--session-key", sessionKey];
}

export default function (pi: ExtensionAPI) {
  let config: Required<ExtensionConfig> | undefined;
  let sessionTitle = "Pi";
  let sessionKey = "";

  const getConfig = (ctx: any): Required<ExtensionConfig> => {
    if (!config) config = loadConfig(ctx);
    return config;
  };

  pi.on("session_start", async (event, ctx) => {
    config = loadConfig(ctx);
    sessionTitle = typeof event?.session?.name === "string" && event.session.name.trim() ? event.session.name : "Pi";
    const nextSessionKey = extractSessionKey(event);
    sessionKey = nextSessionKey;
    if (config.enabled) {
      ctx.ui.notify("speakup extension active", "info");
      getVersion(config.command, ctx);
    }
  });

  pi.on("message_end", async (event, ctx) => {
    const cfg = getConfig(ctx);
    if (!cfg.enabled) return;
    const nextSessionKey = extractSessionKey(event);
    if (nextSessionKey) {
      sessionKey = nextSessionKey;
    } else if (event?.message?.role === "assistant") {
      sessionKey = "";
    }

    const role = event?.message?.role;
    if (cfg.onlyAssistant && role !== "assistant") return;

    const text = extractText(event?.message);
    if (!text) return;

    const eventType = role === "assistant" ? "final" : "info";
    const payload = {
      message: text,
      event: eventType,
      agent: "pi",
      sessionName: sessionTitle,
      sessionKey,
      metadata: {
        source: "pi-message_end",
        role,
        sessionName: sessionTitle,
        sessionKey,
      },
    };

    runNotifier(cfg.command, cfg.args, payload, ctx);
  });

  pi.registerCommand("speakup", {
    description: "Toggle speakup extension notifications or replay recent messages",
    handler: async (args, ctx) => {
      const cfg = getConfig(ctx);
      const input = (args || "status").trim();
      const [cmd, rawCount] = input.split(/\s+/, 2);
      const normalized = cmd.toLowerCase();

      if (normalized === "on") {
        cfg.enabled = true;
        ctx.ui.notify("speakup enabled", "info");
      } else if (normalized === "off") {
        cfg.enabled = false;
        ctx.ui.notify("speakup disabled", "info");
      } else if (normalized === "replay") {
        if (!sessionKey) {
          ctx.ui.notify("speakup: current Pi session key is unavailable", "error");
          return;
        }
        const count = rawCount && /^\d+$/.test(rawCount) ? rawCount : "1";
        const child = spawn(cfg.command, buildReplayCommandArgs(cfg, count, sessionKey), {
          stdio: ["ignore", "pipe", "pipe"],
        });
        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (d) => (stdout += d.toString()));
        child.stderr.on("data", (d) => (stderr += d.toString()));
        child.on("error", (err: any) => {
          ctx.ui.notify(`speakup: replay failed to start: ${err?.message ?? err}`, "error");
        });
        child.on("close", (code) => {
          if (code === 0) {
            ctx.ui.notify(`speakup replayed ${count} notification${count === "1" ? "" : "s"}`, "info");
            return;
          }
          const detail = stderr.trim() || stdout.trim() || `exit code ${code}`;
          ctx.ui.notify(`speakup: replay failed (${detail})`, "error");
        });
      } else {
        ctx.ui.notify(`speakup is ${cfg.enabled ? "enabled" : "disabled"}`, "info");
      }
    },
  });
}
