CrypBot
A Python-based cryptocurrency futures trading bot with automated technical analysis, risk management, and self-monitoring capabilities.
Overview
CrypBot is an automated trading system for Binance Futures that combines multiple technical indicators to identify trading opportunities. It features ATR-based stop-loss/take-profit management, position monitoring, and comprehensive trade execution with safety mechanisms.
![Dashboard Sample](DashBordSample_1.png)
Core Features

Technical Analysis: Chandelier ZLSMA, Support/Resistance levels, Buy/Sell Pressure Scanner
Risk Management: ATR-based stop-loss and take-profit with configurable ratios
Position Monitoring: Self-monitoring system with 0.3s polling interval
Trade Execution: Automatic order placement with retry logic and position verification
Safety Mechanisms: 1.5% liquidation safety buffer, reliable price monitoring

Architecture
CrypBot/
├── ExecutionHub/
│   ├── DisplayFuture.py              # Live chart display
│   └── FutureTradeExecution.py       # Trade execution engine
├── IndicatorsHub/
│   ├── Buy_Sell_Pressure_Scanner.py  # Order flow analysis
│   ├── Chandelier_ZLSMA_Filter.py    # Trend filter
│   ├── Chandelier_ZLSMA.py           # Main indicator
│   ├── SMC_FGV.py                    # Smart Money Concepts
│   ├── SMC.py                        # Market structure
│   ├── Support_Resistance_Future.py  # S/R levels
│   └── Up_Down_Trend_Scanner.py      # Trend detection
├── Dashboard.ipynb                   # Monitoring interface
├── Live_Trade_Future.ipynb          # Main trading notebook
└── Coin_List.csv                    # Trading pairs configuration
Key Components
Signal Generation

Scans active symbols from support/resistance levels
Identifies long signals when near resistance
Identifies short signals when near support
Filters signals through Chandelier ZLSMA

Trade Parameters

Leverage: Configurable (e.g., 10x)
Position sizing: Risk-based calculation
Stop-loss: ATR multiplier (e.g., 2.0x)
Take-profit: Risk-reward ratio (e.g., 1:2)

Monitoring System

Real-time position tracking
Automatic stop-loss/take-profit execution
External position closure detection
Trade exit recording with PnL tracking

Trade Flow

Scanner detects support/resistance proximity
Chandelier ZLSMA confirms trend direction
Trade executed with calculated position size
Self-monitoring loop activates (0.3s interval)
Automatic exit on stop-loss, take-profit, or manual close
Trade results recorded with duration and PnL

Risk Controls

Liquidation buffer: 8.3% safety distance from liquidation price
ATR-based stops: Dynamic stop placement based on volatility
Position verification: Confirms order execution before monitoring
Error handling: Retries and fallback mechanisms for API calls

Recent Performance
Based on logs:

MOCAUSDT: -0.96% (4.0 min duration)
EPTUSDT: -5.01% (17.9 min duration)

Requirements
See requirements.txt for dependencies. Key libraries:

pandas: Data manipulation
IndicatorsHub: Custom technical indicators
ExecutionHub: Trade execution framework

Configuration
Trading pairs configured in Coin_List.csv. Adjust parameters in the trading notebook:

Leverage levels
ATR multipliers
Risk-reward ratios
Monitoring intervals

Notes

System operates on Binance Futures USDT perpetual contracts
Real-time monitoring requires active connection
All critical fixes applied and verified
Ultra-fast monitoring at 0.3s intervals

Disclaimer
Trading cryptocurrencies involves substantial risk of loss. This bot is for educational purposes only. Use at your own risk.