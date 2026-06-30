# carson-agent

**A personal AI agent framework powered by Claude** — voice assistant, algorithmic crypto trading bot, and AI-driven YouTube content pipeline, all running on a single Windows machine without Docker.

> Built for daily use, not demos. Everything here runs 24/7 in production.

---

## What's inside

### 🗣 Jarvis — Voice AI Assistant
Say *"Hey Jarvis"* → speak in natural Chinese → she hears, thinks, and **controls your computer**.

- **Wake-word detection** via openWakeWord (offline, instant)
- **Speech-to-text** via faster-Whisper (local GPU/CPU)
- **Three-brain routing architecture:**
  - Local actions (open apps, volume, screenshots, window switching) → executed in <100ms, no cloud
  - Quick answers (chat, Q&A) → Claude API direct, 1–2s
  - Unlimited power (file ops, scripts, browsing, coding) → Claude Code, full capability
- **Computer vision** — "look at my screen" → screenshot → Claude vision → spoken answer
- **Edge-TTS voice synthesis** — streams audio sentence-by-sentence for low latency
- **Iron Man HUD dashboard** — glassmorphic status panel synced to Jarvis state (idle/listening/thinking/speaking)
- **Safety by default** — destructive actions require `JARVIS_FULL_POWER=1` to unlock

```bash
# Install
uv pip install -r jarvis/requirements.txt

# Run (safe mode)
python jarvis/jarvis.py

# Run (full power — Jarvis can do anything)
set JARVIS_FULL_POWER=1 && python jarvis/jarvis.py
```

---

### 📈 trading_bot — Multi-agent Crypto Trading Bot
Fully automated algorithmic trading on Pionex exchange with paper trading and live execution.

- **Clean architecture** — `Strategy / DataFeed / RiskManager / Executor` interfaces; swap any component without touching others
- **Dual data source** — Pionex live feed + TradingView cross-validation; halts trading if sources diverge >0.5%
- **SuperTrend strategy** with configurable ATR and multiplier
- **Walk-forward backtester** — realistic out-of-sample validation, no look-ahead bias
- **Risk guardrails** — per-trade stop-loss, daily max loss ceiling, position size limits
- **Paper trading by default** — `dry_run: true` in config; live trading requires explicit opt-in
- **ntfy push notifications** — alerts to your phone when running unattended

```bash
# Backtest
python trading_bot/run_backtest.py --config trading_bot/config/config.example.yaml

# Live paper trading
python trading_bot/main.py --config trading_bot/config/config.yaml

# Parameter sweep
python trading_bot/sweep.py
```

---

### 🎬 youtube_channel — AI YouTube Content Pipeline
Fully automated faceless YouTube channel that produces and publishes educational trading videos.

- **Script generation** — Claude writes scripts optimized for YouTube Shorts algorithm (30–45s, hook-first, loop-friendly titles)
- **Voice synthesis** — Kokoro TTS (free, local) or MiniMax API; Edge-TTS fallback
- **Thumbnail generation** — automated with Pillow; brand-consistent templates
- **Video rendering** — FFmpeg backend (pure pipeline, no moviepy frame-by-frame bottleneck)
- **Multi-platform publishing** — YouTube + Instagram + TikTok via Postiz (self-hosted)
- **Analytics feedback loop** — completion rate data feeds back into topic selection and script style
- **Department architecture** — separate agents for script, thumbnail, TTS, render, publish, analytics, competitor research

```bash
# Produce one short
python youtube_channel/scripts/produce_batch.py --count 1

# Full daily run
python youtube_channel/scripts/run_all.py
```

---

## Architecture

```
carson-agent/
├── jarvis/                  # Voice AI assistant
│   ├── jarvis.py            # Wake-word → STT → brain routing → TTS
│   ├── computer.py          # Local computer control (apps/volume/windows/vision)
│   ├── dashboard/           # Iron Man HUD web dashboard
│   └── web/                 # Browser-based Jarvis UI (Three.js orb + audio reactive)
│
├── trading_bot/             # Crypto trading system
│   ├── core/                # Abstract interfaces
│   ├── strategy/            # SuperTrend + extensible strategy base
│   ├── data/                # Pionex feed + TradingView cross-check
│   ├── execution/           # Paper executor + live Pionex client
│   ├── risk/                # Position sizing, stop-loss, daily loss ceiling
│   └── backtest/            # Walk-forward backtesting engine
│
└── youtube_channel/         # AI content pipeline
    ├── scripts/             # Department agents (script/thumb/tts/render/publish/analytics)
    └── assets/              # Brand assets, fonts, overlays
```

---

## Design principles

**No Docker.** Everything runs as plain Python processes. Simpler to debug, simpler to cron.

**Claude as the core.** Jarvis delegates to Claude Code for open-ended tasks. The YouTube pipeline uses Claude for script writing and topic research. The trading bot uses Claude for log analysis and strategy explanation.

**Production-first.** This isn't a toy — Jarvis runs daily, the trading bot runs on a cloud VPS, and the YouTube pipeline has published 200+ videos. Edge cases, error handling, and graceful degradation are built in.

**Secrets never in code.** `.env` / `config.yaml` are gitignored. Only `.example` templates are committed.

---

## Requirements

- Python 3.11+
- Windows 10/11 (Jarvis uses Win32 APIs for computer control; trading bot and YouTube pipeline are cross-platform)
- [Claude Code CLI](https://claude.ai/code) for Jarvis full-power mode
- Pionex account for live trading (paper mode works without one)

---

## License

MIT
