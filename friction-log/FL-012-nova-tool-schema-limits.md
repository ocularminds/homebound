# FL-012 — Amazon Nova tool schema limits

- **Date:** 2026-10-01
- **Component:** Bedrock Converse tool definitions from the HomeBound MCP server
- **Environment:** Amazon Nova Lite inference profile in `us-east-1`; MCP Python SDK 2.2.0
- **Expected:** Forward the MCP tool's JSON Schema unchanged to Bedrock Converse so the agent can call the declared action.
- **Observed:** MCP's generated schemas include annotations and open-ended dictionary properties. Amazon Nova's Converse tool schema accepts only `type`, `properties`, and `required` at the top-level object; dynamic nested objects are not part of its supported subset.
- **Error:** The MCP schema is incompatible with the documented Amazon Nova tool-schema subset and may be rejected by Converse.
- **Impact:** Bedrock could not reliably request actions using the live, model available in the configured AWS account.
- **Investigation:** Checked the official Nova tool definition guide and confirmed the schema restriction and recommendation to use temperature 0 for tool selection.
- **Workaround:** At the Bedrock boundary only, present arbitrary context/parameter dictionaries as JSON-encoded strings, remove unsupported schema annotations, parse and validate those values, then pass ordinary dictionaries to MCP. The MCP action schema remains structured and unchanged.
- **Resolution:** Added Nova-specific input-schema adaptation and malformed-JSON rejection before MCP invocation; tool selection uses temperature 0.
- **Upstream/documentation gap:** The MCP server's schema format and Nova's supported subset do not align directly; the adapter keeps both protocols intact.
- **Status:** Resolved; covered by orchestration tests and pending one live, non-executing tool-selection smoke request.

Reference: [AWS: Defining a tool for Amazon Nova](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html).
