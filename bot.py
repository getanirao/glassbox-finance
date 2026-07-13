import os
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
            self._synced = True
            print(f"  [Bot] Slash commands synced to {len(self.guilds)} guild(s).")


def admin_check(interaction: discord.Interaction) -> bool:
    return True


def trader_check(interaction: discord.Interaction) -> bool:
    return True


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
        engine = self.bot.engine
        if engine:
            engine.pause()
        from engine import handle_reset
        handle_reset()
        if engine:
            engine.clear_trigger()
            engine.resume()
        await interaction.response.send_message("State files cleared. Ready for fresh run.", ephemeral=False)

# ── Query Cog ────────────────────────────────────────────────────────────

class QueryCog(commands.Cog):
    def __init__(self, bot: GlassboxBot):
        self.bot = bot

    @app_commands.command(name="holdings", description="Show current competition portfolio holdings")
    @app_commands.check(trader_check)
    async def cmd_holdings(self, interaction: discord.Interaction):
        from engine import load_competition_ledger
        ledger = load_competition_ledger()
        if not ledger["holdings"]:
            await interaction.response.send_message("No current holdings.", ephemeral=True)
            return
        lines = [f"**Competition Portfolio**  |  Cash: ${ledger['cash_balance']:,.2f}"]
        lines.append("```")
        header = f"{'Ticker':<8} {'Shares':>8} {'Avg Price':>12} {'Value':>14}"
        lines.append(header)
        lines.append("-" * len(header))
        total = 0
        for ticker, pos in ledger["holdings"].items():
            try:
                import yfinance as yf
                stock = yf.Ticker(ticker)
                price = stock.fast_info.last_price
            except Exception:
                price = 0
            val = pos["shares"] * price
            total += val
            lines.append(f"{ticker:<8} {pos['shares']:>8} ${pos['avg_price']:>9,.2f} ${val:>11,.2f}")
        lines.append("-" * len(header))
        lines.append(f"{'TOTAL':<8} {'':>8} {'':>12} ${total:>11,.2f}")
        lines.append("```")
        await interaction.response.send_message("\n".join(lines), ephemeral=False)

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
    async def cmd_trade(self, interaction: discord.Interaction, ticker: str, action: str, shares: int, price: float):
        from engine import record_trade, load_competition_ledger
        ticker = ticker.upper()
        action = action.lower()
        if action not in ("buy", "sell"):
            await interaction.response.send_message("Action must be `buy` or `sell`.", ephemeral=True)
            return
        if shares <= 0:
            await interaction.response.send_message("Shares must be positive.", ephemeral=True)
            return
        if price <= 0:
            await interaction.response.send_message("Price must be positive.", ephemeral=True)
            return
        ok = record_trade(ticker, action, shares, price)
        if not ok:
            await interaction.response.send_message(f"Cannot sell {ticker} — not in ledger.", ephemeral=True)
            return
        ledger = load_competition_ledger()
        pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else 0
        lines = [
            f"**Trade Logged** — {action.upper()} {shares} {ticker} @ ${price:.2f}",
            f"Cash: ${ledger['cash_balance']:,.2f}  |  Portfolio: ${pv:,.2f}",
            f"Holdings: {len(ledger['holdings'])} positions",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=False)

    @app_commands.command(name="hold", description="Confirm a HOLD recommendation from the engine")
    @app_commands.check(trader_check)
    async def cmd_hold(self, interaction: discord.Interaction, ticker: str):
        from engine import record_hold
        ticker = ticker.upper()
        record_hold(ticker)
        await interaction.response.send_message(f"HOLD confirmed for {ticker}.", ephemeral=False)

    @app_commands.command(name="help", description="Show available commands and their usage")
    async def cmd_help(self, interaction: discord.Interaction):
        lines = [
            f"**Glassbox Finance — Bot Commands**",
            f"",
            f"**Query Commands** (Trader + Admin):",
            f"`/status` — Engine state, clock, portfolio value",
            f"`/holdings` — Current competition portfolio positions",
            f"`/news` — News cache summary with sentiment",
            f"`/history` — Portfolio value history (last 20)",
            f"`/chart` — Performance chart image",
            f"`/trade` — Log a real buy/sell (ticker, buy/sell, shares, price)",
            f"`/hold` — Confirm a HOLD recommendation (ticker)",
            f"`/help` — This message",
            f"",
            f"**Admin Commands** (Admin role only):",
            f"`/pause` — Pause the engine loop",
            f"`/resume` — Resume the engine loop",
            f"`/stop` — Gracefully stop the engine (preserves cache)",
            f"`/clear` — Clear news cache, state files, and competition ledger",
            f"",
            f"No role restrictions — all commands available to everyone.",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=False)
