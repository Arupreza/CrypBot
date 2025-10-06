🤖 CrypBot: Automated Cryptocurrency Futures Trading Bot
A Python-based trading bot for Binance Futures that uses automated technical analysis and robust risk management to execute trades.

🚀 Overview
CrypBot is an automated trading system designed to operate on Binance USDT perpetual futures contracts. It integrates a multi-indicator strategy to identify and act on trading opportunities, featuring a high-frequency monitoring system and dynamic risk controls based on market volatility.

📈 Trading Strategy
The bot's strategy is based on identifying potential market reversals or continuations at key price levels, filtered by trend confirmation.

Signal Generation: The system scans a user-defined list of trading pairs (Coin_List.csv) to identify when the price is approaching significant Support or Resistance levels.

Long Signal: A potential long entry is identified when the price nears a key support level.

Short Signal: A potential short entry is identified when the price nears a key resistance level.

Signal Filtration: Every potential signal is filtered through the Chandelier ZLSMA indicator to ensure the trade aligns with the underlying market trend. A trade is only initiated if the trend confirms the direction of the signal.

Execution: Once a signal is confirmed, the bot calculates the position size based on pre-defined risk parameters and executes the trade.

✨ Key Features
Technical Analysis Engine: Utilizes a combination of Support/Resistance levels, Chandelier ZLSMA (Zero Lag Smoothed Moving Average), and order flow analysis (Buy/Sell Pressure Scanner).

Dynamic Risk Management: Implements ATR (Average True Range) to set dynamic stop-loss and take-profit levels, adapting to current market volatility.

High-Frequency Monitoring: A self-monitoring loop checks open positions at a high frequency (configurable, e.g., 0.3s) to manage exits precisely.

Automated Trade Execution: Handles order placement, verification, and management with built-in retry logic for API calls.

🏗️ Architecture
The project is structured into distinct modules for indicators and execution logic.

CrypBot/
├── ExecutionHub/                   # Handles trade execution and management
│   ├── DisplayFuture.py          # Renders live chart data
│   └── FutureTradeExecution.py   # Core trade execution engine
├── IndicatorsHub/                  # Contains all technical indicators
│   ├── Buy_Sell_Pressure_Scanner.py # Order flow and volume analysis
│   ├── Chandelier_ZLSMA_Filter.py   # Trend-confirming filter
│   ├── Chandelier_ZLSMA.py          # Main trend-following indicator
│   ├── SMC_FGV.py                   # Smart Money Concepts (Fair Value Gaps)
│   ├── SMC.py                       # Smart Money Concepts (Market Structure)
│   ├── Support_Resistance_Future.py # S/R level detection
│   └── Up_Down_Trend_Scanner.py     # General trend direction scanner
├── Dashboard.ipynb                 # Jupyter notebook for monitoring bot performance
├── Live_Trade_Future.ipynb         # Main notebook to run the live trading bot
├── requirements.txt                # Project dependencies
└── Coin_List.csv                   # User-defined list of trading pairs

🛠️ Installation
Clone the repository:

git clone <repository-url>
cd CrypBot

Create and activate a virtual environment:

python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

Install the required dependencies:

pip install -r requirements.txt

⚙️ Configuration
API Credentials: Create a .env file in the root directory and add your Binance API keys:

API_KEY="YOUR_API_KEY"
API_SECRET="YOUR_API_SECRET"

The execution scripts must be updated to load these variables.

Trading Pairs: Edit Coin_List.csv to include the USDT perpetual futures symbols you want the bot to trade (e.g., BTCUSDT, ETHUSDT).

Strategy Parameters: Open the Live_Trade_Future.ipynb notebook and adjust the core trading parameters:

Leverage

Risk-Reward Ratio

ATR multiplier for stop-loss

Position sizing rules

▶️ Usage
The primary entry point for live trading is the Jupyter Notebook.

Ensure your virtual environment is activated.

Launch Jupyter Notebook or JupyterLab:

jupyter notebook

Open Live_Trade_Future.ipynb and run the cells sequentially to start the bot.

🛡️ Risk Controls
The system has multiple layers of risk management to protect capital.

ATR-Based Stops: Stop-losses are not fixed; they are calculated using an ATR multiplier. This allows them to be wider during high volatility and tighter during low volatility.

Liquidation Prevention: With proper leverage and ATR-based stop-losses, a position should be closed by the stop-loss long before it approaches the liquidation price. The "8.3% safety distance" is a calculated outcome of the stop-loss placement, not a separate mechanism.

Position Verification: The bot confirms that an order has been successfully executed on the exchange before it begins the monitoring process.

⚖️ Disclaimer
Trading cryptocurrencies involves substantial risk and is not suitable for all investors. This software is provided for educational purposes only. Do not risk money that you cannot afford to lose. The developers assume no liability for any financial losses incurred. Use at your own risk.