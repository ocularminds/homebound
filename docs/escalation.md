# Household approval in the Alexa simulator

When a child asks to disable the alarm, HomeBound captures that conversation as simulation context and submits the exact request through MCP and AgentSafe. Decionis evaluates the household policy and, when its tenant connection is configured, opens its native Presence approval. Saying “Mum approved it” is a request to check that approval; it never grants permission locally.

The screen shows **Your parent needs to approve that first**, followed by an approval card with the device request, returned Presence status, and remaining approval window. A parent completes the ceremony in Decionis Presence. The official AgentSafe 0.2.5 managed handoff contains status and expiry, but deliberately does not return an invitation URL or Presence credential to HomeBound. The frontend does not manufacture a link or provide an Approve button.

## Continuing the conversation

- **Automatic updates:** while the page is visible and the conversation is idle, the browser checks a saved handoff about every five seconds. It waits while the user speaks or Alexa replies. A check leaves microphone capture running; a new utterance can be transcribed while that check finishes. Pending checks update the card without adding repeated messages to the conversation.
- **Check by voice or button:** say “check approval,” “has Mum approved the alarm?”, or choose **Check approval**. The exact phrase “check approval” also works if Bedrock is unavailable. The server selects only handoffs saved in that browser session. If there is more than one, Alexa asks which device to check.
- **Completion:** AgentSafe asks Decionis to verify approval and reauthorize the saved intent. Only its new `ALLOW` and confirmed `PERFORMED` result produces a spoken completion and a device snapshot. The listener resumes after that reply. Approval alone does not dispatch a device from the browser.
- **Expiry or decline:** the authority's terminal result removes the card and explains that no action ran. The displayed countdown is informational; it never makes a local authorization decision. A final check resolves a window that has elapsed.
- **Unavailable check:** a temporary authority failure retains the original handoff and stops automatic checks. A manual check can continue after the service recovers. A lost response or unknown execution result stops ordinary UI resumes; the action record needs review because the device may already have run.
- **Cancel:** an unsubmitted conversation request can be cancelled. If a request has already escalated, “cancel” pauses automatic checks and directs the parent to decline in Presence. HomeBound cannot revoke the native approval and does not claim that it did. Completed device actions are not undone.

A repeat request for a device already waiting on approval does not create another escalation. Other conversation can continue. Clearing conversation retains approval cards and evidence. Reloading the page restores handoffs belonging to that session; a server restart or session expiry still requires the existing durable escalation CLI.

## Enforcement boundary

The MCP process stores the full AgentSafe handoff privately in SQLite. The browser receives only a display label, session-owned correlation ID, status, expiry, and check availability. It cannot change the intent, select an approver, add a receipt, or supply approval evidence. Resume checks within the MCP process are serialized so an older response cannot replace newer handoff state. The official executor still owns grant binding, claiming, expiry, idempotency, and dispatch.

The approval deadline is the earlier of the managed approval expiry and the captured intent expiry. A temporary authority failure is not recorded as a denial. `UNKNOWN_AFTER_DISPATCH` and a lost executor response are reported as unknown, rather than as proof that an action did not run. A queued spoken update cannot replace a newer device snapshot.

## Live prerequisite identified on 2026-10-07

The fresh child escalation fails before a handoff exists. An instrumented request through the official SDK and its guarded transport returned:

```text
HTTP 503
PRESENCE_TENANT_CONNECTION_NOT_CONFIGURED
```

AgentSafe 0.2.5 exposes this upstream response as `AUTHORITY_REQUEST_FAILED`. This is a missing Decionis-to-Presence tenant connection, not an AWS session problem or a browser microphone failure. No local device dispatch was attempted during the diagnostic, and the live web request did not execute a device.

The Decionis tenant used by the private home policy binding needs its Presence connection configured. Its parent approver must also be enrolled in that workspace with the existing `APPROVER` role, matching the trusted approver configured for AgentSafe. Connection credentials belong in Decionis's managed integration; do not add a Presence API key to the HomeBound browser or switch to direct approval to work around this failure. Once the connection is available, make a fresh child request and complete the real parent ceremony within the policy's 60-second approval window.

## Verification

The Python suite covers outage recovery, exact handoff reuse, concurrent checks, expired and declined approvals, unknown execution, voice claims, multiple pending requests, session isolation, request deduplication, cancellation, and quiet background checks. The existing Node voice tests also pass.

Browser verification uses an explicitly labelled local approval fixture, separate from the live authority: pending checks preserve one microphone connection, approval completion is spoken once, and listening resumes. The approval card fits the 475 × 763 panel without scrolling or horizontal overflow. Fixture completion is not a successful native Presence ceremony. The real ceremony remains blocked by the tenant connection above.
