Order fill functionality

## change the trade ledger to have target fill and actual fill 
--> change the table to be instead of quanityt, it should be filled_quantity and a target quantity 
--> then once the target matches the filled quantity then set the filled at field. 
--> also set the filled price once the order is filled. 

then at the beginning of everyday if there are any orders that are not fully filled then submit the partil fill orders for them.

Here's the plan — 5 files edited, 1 new file.

1. domain/trades.py — rework the record

Replace TradeFill with TradeOrder: strategy, symbol, side, target_quantity, limit_price, max_entry_price, submitted_at. Same validation style. (max_entry_price rides along so the morning job can recompute limits without needing the Portfolio object.)

2. data/repository/ledger.py — the main change

- record_order(order: TradeOrder) -> trade_id — writes the row at submission: target_quantity, filled_quantity=0, filled_cost=0, filled_price=None, filled_at=None, paper flag.
- apply_fill(strategy, trade_id, quantity, price) — read-modify-write: bump filled_quantity, accumulate filled_cost (total dollars, so avg price = cost/qty is exact); when filled_quantity >= target_quantity, set filled_price (the weighted avg) and filled_at.
- load_open_orders(strategy) -> DataFrame — rows where filled_at is null.
- load_trades stays as-is.
- Update the module docstring (no longer append-only).

3. workflows/enter_positions.py — hook in at submission

In submit_entry, after submit_order(): call record_order, and register order.identifier → trade_id in a dict the strategy owns. Replaces the existing TODO. submit_entry returns the mapping info instead of just bool.

4. New: workflows/fill_open_orders.py — the morning job

- load_open_orders → for each row: remainder = target - filled, fresh limit via the same entry_limit_price logic (today's last price, capped at the row's max_entry_price), submit a DAY limit order, map new order ID → same trade_id.
- Reuses the limit-price helper from enter_positions.py — no duplication.

5. strategies/csf_champions/strategy.py — wire the lifecycle

- initialize: create self.order_trade_ids: dict[str, str] (order ID → ledger trade_id).
- Add on_partially_filled_order and on_filled_order hooks → look up trade_id, call apply_fill. Both guarded with if self.is_backtesting: return (ledger is live/paper only, per existing convention).
- on_trading_iteration: call fill_open_orders(self) — it no-ops when nothing is open.

6. data/repository/__init__.py + tests

Update exports, and rewrite test_record_fill_serializes_domain_record in tests/data/test_repository_contracts.py for the new schema (same fake-table monkeypatch pattern, plus a test for apply_fill's averaging/completion logic).

Scope notes:
- The existing trade-ledger DynamoDB table needs no migration — DynamoDB is schemaless, only the keys (strategy/trade_id) matter, and those don't change.
- Not included (deliberately): linking ideas → ledger (update_idea_status), and the "give up after N days" rule. Both easy follow-ups; keeping this change focused on the fill loop.
- One known gap to flag: the order.identifier → trade_id map is in-memory, so if the process restarts mid-day, fills reported after restart can't find their row until the next morning job reconciles. Acceptable for now; fixing it properly means persisting the order ID on the row.

Want me to go ahead?