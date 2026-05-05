# Phase-Wise Status — May 1, 2026

## Current Snapshot

- Focus area: backend resilience hardening around ai_router/provider status paths and extracted operator/public runtime routes, plus the first authenticated Phase 5 text-admin gateway on top of the existing manual-controls authority boundary.
- Latest focused validation: `python -m pytest tests/test_phase1_router_regressions.py -q --tb=no` -> `145 passed`.
- Latest full backend validation: `python -m pytest tests/ -q --tb=no` -> `410 passed`.
- Latest slice validation (2026-05-05): `python -m pytest tests/test_phase1_router_regressions.py -k "text_command_route or equity_scanner_toggle_route_delegates_to_manual_controls" -q --tb=no` -> `4 passed`.
- Latest live market validation (2026-05-05): a fresh token-backed validation instance on port `8064` reached `/health` healthy with `market_open=true`, started Dhan MarketFeed, returned `200` from the new `/api/controls/text-command` dry-run route during an active cycle, and on a wider re-probe returned `/api/system/telemetry` with `cycle_status=in_progress`, `current_phase=decision`, `cycle_timing_health.total_ms ≈ 55,286`, plus non-null route-level OFI for `RELIANCE` with `weighted_ofi=-0.1584` and `levels_with_data=40`.
- Latest live runtime findings: the first fresh-start market-hours reads for `/api/system/telemetry` and `/api/charts/volume-profile/RELIANCE` still timed out once under active-cycle startup pressure, but the wider follow-up re-probe succeeded, which narrows the remaining live sensitivity to first-probe startup pressure rather than a persistent route failure. The Redis bool-serialization warning is closed, the telemetry route prefers cached `session_telemetry` plus batched Redis reads, `/health` serves a short-lived cached snapshot, the merged StrategyAgent GenAI validation prompt now builds once per batch, and the first Phase 5 text-admin gateway now proves authenticated dry-run command parsing works during live market load without mutating runtime.

## Phase 1 — Router And Runtime Hardening

Status: active, green

Completed in the current hardening wave:

- `/health` now prefers the `vertex_ai_client.status()` contract and no longer eagerly calls legacy availability fallback when status already supplies `available`.
- `/metrics` now returns a Prometheus-safe fallback comment when metric export fails.
- `/api/ai/router` and `/api/ai/cost` now return safe error payloads instead of surfacing dependency exceptions.
- `/api/ai/budget` now returns unchanged budget values plus an explicit error payload when tracker updates fail, while still persisting successful updates to Redis.
- `/options/chain/{symbol}` now returns an explicit empty-chain fallback payload when live chain fetch or item serialization fails, instead of surfacing a route exception.
- `/options/greeks/{position_id}` now returns an empty-greeks fallback payload plus an explicit error field when the greeks engine fails, instead of surfacing a route exception.
- `/options/positions` now returns a safe empty portfolio summary plus an explicit error field when the shared portfolio summary read fails, instead of surfacing a route exception.
- `/options/validate` now returns a safe zero-config payload plus an explicit error field when SEBI validator configuration is unavailable, instead of surfacing a route exception.
- `/api/options/dhan-chain` now returns a safe empty-chain payload plus an explicit error field when Dhan chain payload shaping fails, instead of surfacing a route exception.
- `/api/options/vp-context` now returns a shape-safe zeroed context payload plus an explicit error field when the VP bridge fails, instead of collapsing the contract down to a partial error-only response.
- `/api/options-scan` now returns contract-preserving default decision fields when individual scan decisions are malformed, instead of surfacing a serialization exception.
- `/api/market/watchlist` now survives malformed Dhan quote rows and keeps returning a shape-safe watchlist item instead of surfacing a quote-row extraction exception.
- `/api/user/watchlist` now falls back to the default watchlist when the cached payload is unavailable or corrupted, instead of surfacing a cache or JSON parse exception.
- `/api/user/watchlist` setter now preserves the sanitized symbol payload when cache persistence fails, instead of surfacing a cache-write exception.
- `/api/market/quote/{symbol}` now preserves the normal quote envelope when the yfinance fallback fails, instead of collapsing to a partial error-only payload.
- `/api/account/fund-limits` now preserves a shape-safe Dhan payload with an explicit error field when the fund-limits fetch fails, instead of surfacing a route exception.
- `/api/controls/command-journal` now falls back safely to audit history and preserves its normal journal payload when cached command history is unavailable or corrupted, instead of surfacing a decode exception from the authenticated control gateway.
- `/api/controls/audit-log` now preserves a safe empty history payload with an explicit error field when cached audit history is unavailable or corrupted, instead of surfacing a decode exception from the authenticated control gateway.
- `/api/broker/status` now preserves the broker-status contract with an explicit error field and disconnected fallback state when broker-client creation fails, instead of surfacing a route exception.
- `POST /api/broker/switch` now returns structured HTTP failure payloads and restores the prior broker setting when reset fails, instead of returning tuple-style errors and leaving partial switch state behind.
- `/api/trading/execution-mode` now preserves the execution-mode selector contract with an explicit error field when runtime lookup fails, instead of collapsing to a tuple-style error response.
- `POST /api/trading/execution-mode` now accepts the JSON body shape used by the settings UI and returns a structured failure payload with explicit error fields when updates fail, instead of relying on query-only input and tuple-style errors.
- `/api/broker/execution-broker` now preserves the full selector contract with an explicit error field when execution-router config resolution fails, instead of collapsing to a tuple-style error response.
- `/options/chain/{symbol}` now survives malformed chain metadata during response shaping, instead of rethrowing while building its fallback payload.
- `POST /api/broker/execution-broker` now returns a structured update payload with explicit error fields and a real HTTP failure status when override persistence fails, instead of a malformed tuple-style response.
- `/ai/status` now survives ai_router initialize/status failures plus vertex/cost status failures while preserving the normal success contract.
- `/positions` now survives broker client creation failures, broker-name failures, and per-position policy snapshot failures while still returning the broader positions payload.
- `/trades` now survives broker client creation failures, broker-name failures, and trade-fetch failures with a safe empty response.
- `/closed_positions` now returns an empty payload when runtime context or agent-manager wiring is unavailable.
- Focused failure-path regressions were added for each slice in `backend/tests/test_phase1_router_regressions.py`.

Current assessment:

- Extracted operator/public runtime endpoints are materially more fault-tolerant than at the start of this wave.
- Success payload contracts were kept stable while exceptions were converted into explicit fallback payloads.
- Router regression coverage has grown incrementally with each slice and is currently green at `145` passing checks.

## Phase 3 — Runtime Authority And Freshness

Status: stable, green

- `tests/test_phase3_cycle_intelligence_freshness.py` is green.
- `tests/test_phase3_day_commander_guards.py` is green.
- `tests/test_phase3_event_bus_authority.py` is green.
- No new Phase 3 code changes were required in this wave; current router hardening work has not regressed runtime freshness or authority behavior.

## Phase 4 — AI Router And Strategy/Execution Guards

Status: stable, green

- Earlier slices removed stale Vertex/Gemini scaffolding from execution, scanner, strategy, universal strategy, sentiment module-level wiring, and option-chain advisory paths while preserving intentional dynamic guard paths where required.
- Phase 4 ai_router and latency guard suites remain green across execution, sentiment, universal strategy, option-chain, vertex client, scanner, strategy, and market-data related tests.
- A fresh market-hours probe on port `8063` re-confirmed the current build's live Phase 4 feed path: `/health` returned `healthy` with `market_open=true`, Dhan MarketFeed connected before companion sockets, 20-level depth subscribed, and route-level OFI was non-null for `RELIANCE`, `HDFCBANK`, and `ITC`.
- The same live run showed the remaining runtime issues are still wall-clock and observability related rather than feed-health related: telemetry reported `cycle_status=in_progress` in `decision` with `sensing` as the bottleneck and initial lightweight health and telemetry reads timed out once under load. Follow-up Phase 4 slices closed the scanner/event-bus Redis bool-serialization warning, reduced `/api/system/telemetry` live-cycle coupling by preferring the persisted `session_telemetry` snapshot plus batched Redis reads, added a short-lived `/health` snapshot so repeated probes do less work while orchestration is active, revalidated both routes at `200` during an after-hours forced sensing cycle on the same validation instance, and now remove repeated StrategyAgent GenAI prompt or token-budget rebuilds from the merged decision batch path.
- Full-suite stability remains intact after each small resilience slice.

## Phase 5 — Text-Admin Copilot Foundation

Status: active, 15%

- The first formal Phase 5 slice is now in code: authenticated `/api/controls/text-command` routing on top of the existing `admin_controls_router` and `manual_controls` authority boundary.
- The gateway supports deterministic intent parsing plus dry-run plan rendering for a bounded command catalog, and it can execute supported intents only by delegating to existing validated manual-control functions.
- Preview, rejected, and execute requests are now journaled so text-admin activity is attributable and reviewable even before a richer approval UX lands.
- Remaining work is explicit approval-backed execution for mutating text commands, broader intent coverage, and operator-facing review or approval flow polish.

## Latest Slice

- Implemented the first adjacent Phase 5 text-admin slice in the authenticated control plane instead of adding a side-channel prompt path.
- `manual_controls` now parses a bounded text-command catalog into deterministic plans, supports dry-run previews by default, records preview or rejected or execute events in the durable command journal, and delegates live execution only through existing validated control-plane helpers such as scanner toggles, regime override, approval timeout, position sizing, and rate-limit updates.
- Added focused router regressions for dry-run preview, delegated execution, and unsupported-command rejection, and validated the slice with `python -m pytest tests/test_phase1_router_regressions.py -k "text_command_route or equity_scanner_toggle_route_delegates_to_manual_controls" -q --tb=no` at `4` passing checks plus a live dry-run probe on port `8064` during market hours.

## Next Slice Candidates

- Add an approval-backed execution path for mutating text commands so dry-run plans can graduate into explicit reviewable control actions instead of direct operator submission.
- Expand the bounded text-command catalog over existing manual-control primitives without bypassing the current authenticated control-plane helpers.
- Re-run the same market-hours probe on a warmed backend instance to verify whether the remaining telemetry or OFI sensitivity is now limited to first-start startup pressure only.