🤖 CrypBot: Automated Cryptocurrency Futures Trading Bot
A production-ready Python trading bot for Binance Futures that uses automated technical analysis and robust risk management to execute trades.

🎯 Project Overview
This repository contains an automated trading system designed to operate on Binance USDT perpetual futures contracts. The bot integrates a multi-indicator strategy to identify and act on trading opportunities, featuring a high-frequency monitoring system and dynamic risk controls based on market volatility.

✨ Key Features
Multi-Indicator Strategy: Combines Support/Resistance levels with the Chandelier ZLSMA for trend-confirmed entry signals.

Dynamic Risk Management: Implements ATR (Average True Range) to set adaptive stop-loss and take-profit levels based on market volatility.

High-Frequency Monitoring: A self-monitoring loop checks open positions at a sub-second interval (configurable) for precise exit management.

Automated Execution: Handles order placement, verification, and management with built-in retry logic.

Performance Tracking: Includes a Jupyter Notebook (Dashboard.ipynb) for monitoring trade performance.

🏗️ Trade Flow Architecture
The bot follows a systematic, event-driven process to execute trades.

graph TD
    A[Scan Coin_List.csv] --> B{Price near S/R Level?};
    B -- Yes --> C{Confirm with Chandelier ZLSMA};
    B -- No --> A;
    C -- Trend Confirmed --> D[Calculate Position Size & SL/TP];
    C -- Trend Not Confirmed --> A;
    D --> E[Execute Trade on Binance];
    E --> F[Enter High-Frequency Monitoring Loop];
    F --> G{SL or TP Hit?};
    G -- Yes --> H[Close Position];
    G -- No --> F;
    H --> I[Log Trade Results];
    I --> A;

    style A fill:#f9f,stroke:#333,stroke-width:2px
    style I fill:#9f9,stroke:#333,stroke-width:2px

📁 Repository Structure
CrypBot/
├── 📂 ExecutionHub/                   # Handles trade execution and management
│   ├── DisplayFuture.py          # Renders live chart data
│   └── FutureTradeExecution.py   # Core trade execution engine
├── 📂 IndicatorsHub/                  # Contains all technical indicators
│   ├── Buy_Sell_Pressure_Scanner.py # Order flow and volume analysis
│   ├── Chandelier_ZLSMA_Filter.py   # Trend-confirming filter
│   ├── Chandelier_ZLSMA.py          # Main trend-following indicator
│   ├── SMC_FGV.py                   # Smart Money Concepts (Fair Value Gaps)
│   ├── SMC.py                       # Smart Money Concepts (Market Structure)
│   ├── Support_Resistance_Future.py # S/R level detection
│   └── Up_Down_Trend_Scanner.py     # General trend direction scanner
├──  Dashboard.ipynb                 # Jupyter notebook for monitoring bot performance
├── Live_Trade_Future.ipynb         # Main notebook to run the live trading bot
├── requirements.txt                # Project dependencies
└── Coin_List.csv                   # User-defined list of trading pairs

🚀 Quick Start
1️⃣ Clone & Setup
git clone [https://github.com/your-username/CrypBot.git](https://github.com/your-username/CrypBot.git)
cd CrypBot
python -m venv venv && source venv/bin/activate  # Linux/Mac
# python -m venv venv && venv\Scripts\activate    # Windows
pip install -r requirements.txt

2️⃣ Configure Environment
Create a .env file in the root directory and add your Binance API keys:

API_KEY="YOUR_API_KEY"
API_SECRET="YOUR_API_SECRET"

Also, edit Coin_List.csv to include your desired trading pairs.

3️⃣ Run the Bot
The primary entry point is the Live_Trade_Future.ipynb notebook. Launch Jupyter and run the cells sequentially to start the bot.

jupyter notebook

4️⃣ Monitor Performance
Open and run Dashboard.ipynb to view live and historical trade data.

📊 Performance
Performance metrics and visualizations can be tracked in Dashboard.ipynb.

📝 Recent Trades (Example)
Pair

PnL (%)

Duration (min)

MOCAUSDT

-0.96%

4.0

EPTUSDT

-5.01%

17.9

Equity Curve
(This is a placeholder image. Your dashboard should generate a similar plot.)

🧩 Troubleshooting
Issue

Solution

API Connection Error

Verify that your API keys in the .env file are correct and have the appropriate permissions (Futures Trading) enabled on Binance.

Bot not placing trades

Check the bot's logs. It may be that no valid signals are being generated. Widen your Coin_List.csv or check indicator parameters.

Incorrect Position Size

Review the risk parameters in Live_Trade_Future.ipynb. Ensure your account balance is being fetched correctly.

🤝 Contributing
Fork the repository.

Create your feature branch: git checkout -b feature/NewIndicator

Commit your changes: git commit -m "Add NewIndicator"

Push to the branch: git push origin feature/NewIndicator

Open a Pull Request.

📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

⚖️ Disclaimer
Trading cryptocurrencies involves substantial risk and is not suitable for all investors. This software is provided for educational purposes only. Do not risk money that you cannot afford to lose. The developers assume no liability for any financial losses incurred. Use at your own risk.