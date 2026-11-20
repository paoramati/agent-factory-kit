// time-tracker.js: OpenCode plugin. Writes the same event log as hooks/track.sh.
// Install: copy to .opencode/plugins/time-tracker.js in your project.
// Event names follow the OpenCode v1 plugin API; check them against your installed version.
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const TimeTracker = async ({ directory, worktree }) => {
  const root = worktree || directory;
  const outDir = join(root, ".agent", "time");
  mkdirSync(outDir, { recursive: true });

  const ticket = () => {
    try { return readFileSync(join(root, ".agent", "current-ticket"), "utf8").trim(); }
    catch { return ""; }
  };

  const write = (session, event, extra = {}) => {
    const rec = {
      ts: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
      agent: "opencode",
      session: session || "nosession",
      event,
      ticket: ticket(),
      ...extra,
    };
    try { appendFileSync(join(outDir, `${rec.session}.jsonl`), JSON.stringify(rec) + "\n"); }
    catch { /* never block the agent */ }
  };

  const sessionOf = (e) =>
    e?.properties?.sessionID || e?.properties?.info?.sessionID || e?.properties?.info?.id || "nosession";

  return {
    event: async ({ event }) => {
      switch (event?.type) {
        case "session.created": write(sessionOf(event), "start"); break;
        case "session.idle":    write(sessionOf(event), "stop"); break;
        case "session.deleted": write(sessionOf(event), "end"); break;
        case "message.updated": write(sessionOf(event), "activity"); break;
        default: break;
      }
    },
    "tool.execute.before": async (input) => write(input?.sessionID, "tool_start", { tool: input?.tool }),
    "tool.execute.after":  async (input) => write(input?.sessionID, "tool_end",   { tool: input?.tool }),
  };
};
