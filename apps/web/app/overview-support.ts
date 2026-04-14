import { activityFeed, trustSignals } from "./console-data";

export { activityFeed, trustSignals };

export const serviceRows = [
  { name: "Web dashboard", state: "Running", note: "Thin client console is available for setup, review, billing, and visibility." },
  { name: "MCP service", state: "Ready", note: "Tool surface is defined for search, queue, packet, review, and answer memory." },
  { name: "API service", state: "Next", note: "Supabase auth, account persistence, and tenant isolation still need wiring." },
  { name: "Worker runtime", state: "Next", note: "Browser execution and async queues will power supported auto-apply later." }
];
