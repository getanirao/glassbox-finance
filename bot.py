import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from config import *


class GlassboxBot(commands.Bot):
    def __init__(self, engine_runner=None):
        intents = discord.Intents.default()
        intents.message_content = False
        intents.guilds = True
        super().__init__(command_prefix="/", intents=intents)
        self.engine = engine_runner
        self._synced = False

    async def setup_hook(self):
        await self.add_cog(EngineCog(self))
        await self.add_cog(QueryCog(self))

        @self.tree.error
        async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            msg = f"Error: {error}"
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=False)
                else:
                    await interaction.followup.send(msg, ephemeral=False)
            except Exception:
                pass

    async def on_ready(self):
        print(f"\n  [Bot] Logged in as {self.user} (ID: {self.user.id})")
        if not self._synced:
            await self.tree.sync()
            for guild in self.guilds:
                await self.tree.sync(guild=guild)
            self._synced = True
            print(f"  [Bot] Slash commands synced (global + {len(self.guilds)} guild(s)).")


def _has_role(interaction: discord.Interaction, *role_names: str) -> bool:
    roles = getattr(interaction.user, "roles", [])
    return any(getattr(role, "name", None) in role_names for role in roles)


def admin_check(interaction: discord.Interaction) -> bool:
    return _has_role(interaction, DISCORD_ADMIN_ROLE)


def trader_check(interaction: discord.Interaction) -> bool:
    return _has_role(interaction, DISCORD_ADMIN_ROLE, DISCORD_TRADER_ROLE)


# ── Engine Cog ───────────────────────────────────────────────────────────

class EngineCog(commands.Cog):
    def __init__(self, bot: GlassboxBot):
        self.bot = bot

    @app_commands.command(name="status", description="Show current engine state and clock status")
    @app_commands.check(trader_check)
    async def cmd_status(self, interaction: discord.Interaction):
        engine = self.bot.engine
        if not engine:
            await interaction.response.send_message("Engine not running.", ephemeral=True)
            return
        st = engine.get_status()
        mode = st.get("mode", "N/A")
        market = st.get("market_state", "N/A")
        last = st.get("last_run_utc", "never")
        uptime = st.get("uptime_start_utc", "unknown")
        paused = st.get("paused", False)
        holdings = st.get("holdings_count", 0)
        pv = st.get("portfolio_value", 0)
        news_last = st.get("news_last_run", "never")
        lines = [
            f"**Glassbox Finance — Competition Engine Status**",
            f"",
            f"Mode: `{mode}`",
            f"Market: `{market}`",
            f"Paused: `{paused}`",
            f"Portfolio: `${pv:,.2f}`  |  Holdings: `{holdings} / {MAX_PORTFOLIO_HOLDINGS}`",
            f"Last Allocation: `{last}`",
            f"Last News Stream: `{news_last}`",
            f"Started: `{uptime}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=False)

    @app_commands.command(name="pause", description="Pause the engine loop (Admin only)")
    @app_commands.check(admin_check)
    async def cmd_pause(self, interaction: discord.Interaction):
        engine = self.bot.engine
        if not engine:
            await interaction.response.send_message("Engine not running.", ephemeral=True)
            return
        engine.pause()
        await interaction.response.send_message("Engine paused.", ephemeral=False)

    @app_commands.command(name="resume", description="Resume the engine loop (Admin only)")
    @app_commands.check(admin_check)
    async def cmd_resume(self, interaction: discord.Interaction):
        engine = self.bot.engine
        if not engine:
            await interaction.response.send_message("Engine not running.", ephemeral=True)
            return
        engine.resume()
        await interaction.response.send_message("Engine resumed.", ephemeral=False)

    @app_commands.command(name="stop", description="Gracefully stop the engine (preserves cache/state)")
    @app_commands.check(admin_check)
    async def cmd_stop(self, interaction: discord.Interaction):
        engine = self.bot.engine
        if not engine:
            await interaction.response.send_message("Engine not running.", ephemeral=True)
            return
        engine.stop()
        await interaction.response.send_message("Engine stopped gracefully. Cache and state preserved.", ephemeral=False)

    @app_commands.command(name="clear", description="Purge news cache, state files, and reset engine")
    @app_commands.check(admin_check)
    async def cmd_clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        engine = self.bot.engine
        if engine:
            stopped_at_boundary = await asyncio.to_thread(engine.pause_and_wait)
            if not stopped_at_boundary:
                await interaction.followup.send("Reset aborted: engine did not reach a safe cycle boundary.", ephemeral=True)
                return
        from engine import handle_reset
        try:
            await asyncio.to_thread(handle_reset)
        except RuntimeError as exc:
            await interaction.followup.send(f"Reset aborted: {exc}", ephemeral=True)
            return
        finally:
            if engine:
                engine.request_state_reload()
                engine.clear_trigger()
                engine.resume()
        await interaction.followup.send("State files cleared. Engine will reload a fresh cache before its next cycle.", ephemeral=True)

# ── Query Cog ────────────────────────────────────────────────────────────

class QueryCog(commands.Cog):
    def __init__(self, bot: GlassboxBot):
        self.bot = bot

    @app_commands.command(name="news", description="Show latest news roundup")
    @app_commands.check(trader_check)
    async def cmd_news(self, interaction: discord.Interaction):
        from engine import load_news_cache, compute_rolling_sentiment, TICKERS, LONG_WINDOW_HOURS
        cache = load_news_cache()
        entries = cache.get("headlines", [])
        if not entries:
            await interaction.response.send_message("No news data cached yet.", ephemeral=True)
            return
        ticker_counts = {}
        for h in entries:
            t = h.get("ticker", "?")
            ticker_counts[t] = ticker_counts.get(t, 0) + 1
        scored = []
        for t, cnt in ticker_counts.items():
            ss, sp, sn, sc = compute_rolling_sentiment(entries, t)
            ls, lp, ln, lc = compute_rolling_sentiment(entries, t, window_hours=LONG_WINDOW_HOURS)
            scored.append((t, cnt, ss, ls))
        top = sorted(scored, key=lambda x: x[2], reverse=True)[:20]
        lines = [f"**News Cache Summary**  |  {len(entries)} total headlines"]
        lines.append(f"Top tickers by short-term sentiment:")
        lines.append("```")
        lines.append(f"{'Ticker':<8} {'Headlines':>10} {'Short Sent':>12} {'21d Sent':>10}")
        lines.append("-" * 42)
        for t, cnt, ss, ls in top:
            lines.append(f"{t:<8} {cnt:>10} {ss:>+11.3f} {ls:>+9.3f}")
        lines.append("```")
        await interaction.response.send_message("\n".join(lines), ephemeral=False)

    @app_commands.command(name="history", description="Show competition portfolio value history")
    @app_commands.check(trader_check)
    async def cmd_history(self, interaction: discord.Interaction):
        from engine import load_competition_ledger, STARTING_CAPITAL
        ledger = load_competition_ledger()
        hist = ledger.get("history", [])
        if not hist:
            await interaction.response.send_message("No portfolio history yet.", ephemeral=True)
            return
        lines = [f"**Competition Portfolio History**  ({len(hist)} entries)"]
        lines.append("```")
        lines.append(f"{'#':<4} {'Value':>12} {'Change':>12}")
        lines.append("-" * 30)
        last_val = STARTING_CAPITAL
        for i, h in enumerate(hist[-20:], start=1):
            v = h["portfolio_value"]
            ch = v - last_val
            lines.append(f"{i:<4} ${v:>9,.2f} ${ch:>+9,.2f}")
            last_val = v
        lines.append("```")
        await interaction.response.send_message("\n".join(lines), ephemeral=False)

    @app_commands.command(name="chart", description="Show latest competition performance chart")
    @app_commands.check(trader_check)
    async def cmd_chart(self, interaction: discord.Interaction):
        from engine import COMPETITION_CHART
        if not os.path.exists(COMPETITION_CHART):
            await interaction.response.send_message("No chart generated yet.", ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(COMPETITION_CHART), ephemeral=False)

    @app_commands.command(name="trade", description="Log a real trade for the competition ledger")
    @app_commands.check(trader_check)
    async def cmd_trade(self, interaction: discord.Interaction, ticker: str, action: str, shares: int, price: float, time: str = ""):
        await interaction.response.defer()
        from engine import record_trade
        ticker = ticker.upper()
        action = action.lower()
        if action not in ("buy", "sell"):
            await interaction.followup.send("Action must be `buy` or `sell`.", ephemeral=True)
            return
        if shares <= 0:
            await interaction.followup.send("Shares must be positive.", ephemeral=True)
            return
        try:
            ledger = record_trade(ticker, action, shares, price, trade_time=time.strip() or None)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else 0
        ts = time if time else ledger["history"][-1]["timestamp"]
        lines = [
            f"**Trade Logged** — {action.upper()} {shares} {ticker} @ ${price:.2f}",
            f"Time: {ts}  |  Cash: ${ledger['cash_balance']:,.2f}  |  Portfolio: ${pv:,.2f}",
            f"Holdings: {len(ledger['holdings'])} positions",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=False)

    @app_commands.command(name="bulk-trade", description="Execute multiple trades from a pasted block")
    @app_commands.check(trader_check)
    async def cmd_bulk_trade(self, interaction: discord.Interaction, block: str):
        await interaction.response.defer()
        from engine import record_trade, record_hold, load_competition_ledger
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        results = []
        for line in lines:
            parts = line.split()
            if len(parts) < 2:
                results.append(f"`{line}` — SKIP (need: TICKER ACTION SHARES PRICE [TIME])")
                continue
            ticker = parts[0].upper()
            action = parts[1].lower()
            if action == "hold":
                if record_hold(ticker):
                    results.append(f"`{ticker} HOLD` — OK")
                else:
                    results.append(f"`{ticker} HOLD` — SKIP (not in ledger)")
                continue
            if len(parts) < 4:
                results.append(f"`{line}` — SKIP (need: TICKER ACTION SHARES PRICE [TIME])")
                continue
            try:
                shares = int(parts[2])
                price = float(parts[3])
            except ValueError:
                results.append(f"`{line}` — SKIP (invalid shares or price)")
                continue
            time_arg = parts[4] if len(parts) >= 5 else ""
            if action not in ("buy", "sell") or shares <= 0:
                results.append(f"`{line}` — SKIP (action must be buy/sell/hold, shares > 0)")
                continue
            try:
                record_trade(ticker, action, shares, price, trade_time=time_arg.strip() or None)
            except ValueError as exc:
                results.append(f"`{ticker} {action.upper()} {shares}` — SKIP ({exc})")
                continue
            results.append(f"`{ticker} {action.upper()} {shares} @ ${price:.2f}` — OK")
        ledger = load_competition_ledger()
        pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else 0
        out = [
            f"**Bulk Trade Results**  |  Cash: ${ledger['cash_balance']:,.2f}  |  Portfolio: ${pv:,.2f}",
            f"Holdings: {len(ledger['holdings'])} positions",
            "```",
            "\n".join(results),
            "```",
        ]
        await interaction.followup.send("\n".join(out), ephemeral=False)

    @app_commands.command(name="hold", description="Confirm a HOLD recommendation from the engine")
    @app_commands.check(trader_check)
    async def cmd_hold(self, interaction: discord.Interaction, ticker: str):
        from engine import record_hold
        ticker = ticker.upper()
        if record_hold(ticker):
            await interaction.response.send_message(f"HOLD confirmed for {ticker}.", ephemeral=False)
        else:
            await interaction.response.send_message(f"Cannot confirm HOLD for {ticker}: it is not in the ledger.", ephemeral=True)

    @app_commands.command(name="help", description="Show available commands and their usage")
    async def cmd_help(self, interaction: discord.Interaction):
        lines = [
            f"**Glassbox Finance — Bot Commands**",
            f"",
            f"**Query Commands** (Trader + Admin):",
            f"`/status` — Engine state, clock, portfolio value",
            f"`/news` — News cache summary with sentiment",
            f"`/history` — Portfolio value history (last 20)",
            f"`/chart` — Performance chart image",
            f"`/trade` — Log an executed buy/sell with its actual fill price",
            f"`/bulk-trade` — One `TICKER ACTION SHARES PRICE [TIME]` per line; `TICKER HOLD` is also accepted",
            f"`/hold` — Confirm a HOLD recommendation (ticker)",
            f"`/help` — This message",
            f"",
            f"**Admin Commands** (Admin role only):",
            f"`/pause` — Pause the engine loop",
            f"`/resume` — Resume the engine loop",
            f"`/stop` — Gracefully stop the engine (preserves cache)",
            f"`/clear` — Clear news cache, state files, and competition ledger",
            f"",
            f"Trader role required for query/trade commands; Admin role required for engine controls.",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=False)
