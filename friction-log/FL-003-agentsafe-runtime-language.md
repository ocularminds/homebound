# FL-003 — Official AgentSafe executor runs on Node.js

- **Date:** 2026-10-01
- **Component:** Decionis AgentSafe
- **Environment:** Python-first HomeBound monorepo; Node.js 20.20.0 is the active default, with Node.js 22.23.2 already installed through `fnm`
- **Expected:** Reuse an existing Python AgentSafe interceptor in-process.
- **Observed:** The official Decionis `@decionis/agentsafe` executor is a Node.js process; the Commerce repository contains a direct Decionis managed-authority integration but not a reusable Python AgentSafe package.
- **Error:** No official Python implementation of this AgentSafe execution boundary was found in the reviewed sources.
- **Impact:** A Python-only in-process implementation would duplicate an existing trusted execution component. The active Node default is v20.20.0 and does not satisfy AgentSafe's documented Node.js engine range, though fnm has Node.js 22.23.2 available. Corepack's pnpm lookup also failed while `registry.npmjs.org` was unreachable.
- **Investigation:** Reviewed the AgentSafe package/runtime docs and the Commerce `PresenceManagedAuthority` path.
- **Workaround:** Keep the application, MCP server, orchestration, and simulator in Python and call the official AgentSafe runtime over its documented HTTP ingress. Use Node.js 22.23.2 (or later) for that process. Do not port its capture, authority, Presence, or grant lifecycle into Python.
- **Resolution:** Planned for Phase 2; switch to the compatible Node.js runtime already available locally and install the official package through a network-enabled package-manager path.
- **Upstream/documentation gap:** No official Python AgentSafe runtime was located; the supported runtime is Node.js.
- **Status:** Workaround selected; runtime switch and package install pending.
