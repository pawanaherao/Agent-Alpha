# Phase-Wise Status — May 1, 2026

## Current Snapshot

- Focus area: backend resilience hardening around ai_router/provider status paths and extracted operator/public runtime routes, including shape-safe fallbacks across public options, account, broker-management, authenticated control history, trading execution-mode, execution-broker, and market-data boundaries.
- Latest focused validation: `python -m pytest tests/test_phase1_router_regressions.py -q --tb=no` -> `145 passed`.
- Latest full backend validation: `python -m pytest tests/ -q --tb=no` -> `410 passed`.
- Latest slice validation (2026-05-04): `python -m pytest backend/tests/test_phase1_router_regressions.py -k "system_telemetry_route_prefers_cached_session_snapshot or system_telemetry_route_preserves_scanner_prefilter_metrics or system_telemetry_route_marks_cycle_timing_in_progress_when_snapshot_is_active"` -> `3 passed`.
- Latest live market validation (2026-05-04 14:37 IST): bounded port `8063` probe reached `/health` healthy with `market_open=true` in `PAPER_TRADING=True`, Dhan MarketFeed connected before companion sockets, 20-level depth subscribed successfully, and `/api/charts/volume-profile/{symbol}` returned non-null OFI for `RELIANCE`, `HDFCBANK`, and `ITC` with `levels_with_data=40`.
- Latest live runtime findings: `/api/system/telemetry` reported the active cycle in `decision` with `sensing` still the dominant bottleneck, the first `/health` and `/api/system/telemetry` reads timed out under live-cycle load before succeeding on wider retry windows, the Redis bool-serialization warning is now closed, and the telemetry route now prefers cached `session_telemetry` plus batched Redis reads to reduce active-cycle coupling. A fresh live re-probe is still pending before the endpoint responsiveness backlog can be reduced.

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
- The same live run showed the remaining runtime issues are still wall-clock and observability related rather than feed-health related: telemetry reported `cycle_status=in_progress` in `decision` with `sensing` as the bottleneck and initial lightweight health and telemetry reads timed out once under load. Follow-up Phase 4 slices closed the scanner/event-bus Redis bool-serialization warning and now reduce `/api/system/telemetry` live-cycle coupling by preferring the persisted `session_telemetry` snapshot plus batched Redis reads instead of serial cache fetches and direct live session-state reads.
- Full-suite stability remains intact after each small resilience slice.

## Phase 5 — Text-Admin Copilot Foundation

Status: gated, 0%

- Phase 5 is already defined in the supplementary SDLC, but it remains blocked on earlier control-plane, AI-authority, and runtime-orchestration exit criteria.
- The practical next work remains the remaining unblocked Phases 1-4 hardening slices rather than early text-admin execution work.
- The latest authenticated command-journal and audit-history hardening is Phase 5-preparatory control-plane work only; formal text-command gateway, intent parsing, dry-run plan rendering, and approval execution remain gated.

## Latest Slice

- Implemented the next bounded Phase 4 live-runtime cleanup slice in `backend/src/api/system_observability_router.py` rather than widening into orchestration or feed code.
- `/api/system/telemetry` now prefers the persisted `session_telemetry` snapshot and batches its Redis reads, which removes avoidable serial cache waits and direct live session-stat coupling during active cycles while preserving the existing response contract.
- Added a focused regression in `backend/tests/test_phase1_router_regressions.py`; the targeted telemetry slice is green at `3 passed`.

## Next Slice Candidates

- Continue the lightweight endpoint responsiveness slice with `/health`, keeping the change route-local and contract-preserving.
- Re-run a bounded market-hours probe after the next route-local responsiveness slice to confirm `/health` and `/api/system/telemetry` stay responsive without widened retry windows.
- Continue scanning extracted operator/public routes for any remaining direct dependency reads that can still escape fallback handling.