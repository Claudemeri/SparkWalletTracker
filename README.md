# Solana Wallet Tracker Bot

A Telegram bot that tracks multi-buy and multi-sell patterns across multiple Solana wallets using the Moralis API.

## Features

- Track multiple Solana wallets
- Detect multi-buy patterns (3+ wallets buying the same token in 6 hours)
- Detect multi-sell patterns (3+ wallets selling the same token in 6 hours)
- Real-time alerts via Telegram
- Track specific tokens across all wallets
- Toggle alerts on/off
- View wallet summaries and activity

## Prerequisites

- Python 3.7+
- Telegram Bot Token
- Moralis API Key
- Required Python packages

## Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/SolanaWalletTracker.git
cd SolanaWalletTracker
```

2. Install required packages:

```bash
pip install python-telegram-bot==13.7 aiohttp python-dotenv requests
```

3. Create a `.env` file in the project root with the following variables:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
MORALIS_API_KEY=your_moralis_api_key
```

## Usage

1. Start the bot:

```bash
python bot.py
```

2. In Telegram, start a chat with your bot and use the following commands:

   - `/start` - Shows the main menu
   - `/menu` - Shows the main menu again
   - `/summary` - Shows a summary of tracked wallets

3. Use the menu buttons to:
   - Add wallets to track
   - Remove tracked wallets
   - List all tracked wallets
   - Track specific tokens
   - Toggle alerts on/off

## Multi-Buy/Multi-Sell Detection

The bot detects multi-buy and multi-sell patterns when:

- 3 or more tracked wallets buy/sell the same token
- All transactions occur within the last 6 hours
- For buys: `subCategory` is "newPosition"
- For sells: `subCategory` is "sellAll"

### Alert Format

Multi-Buy Alert:

```
🟢 Multi Buy Alert!

[amount of wallets that bought] wallets bought [Token Symbol] in the last 6 hours!
Total: [total amount bought in SOL accross all wallets]

[Token Address]
```

Multi-Sell Alert:

```
🔴 Multi Sell Alert!

[amount of wallets that sold] wallets sold [Token Symbol] in the last 6 hours!
Total: [total amount sold in SOL accross all wallets]

[Token Address]
```

## Data Storage

The bot stores data in three JSON files:

- `wallets.json` - List of tracked wallets
- `tracked_tokens.json` - List of tracked tokens
- `transactions.json` - History of multi-buy/multi-sell transactions

## Moralis API Integration

The bot uses the Moralis API to fetch transaction data:

- Endpoint: `https://solana-gateway.moralis.io/account/mainnet/{wallet_address}/swaps`
- Checks transactions every minute
- Filters transactions from the last 6 hours
- Processes transaction types:
  - `newPosition` for buys
  - `sellAll` for sells

## Error Handling

The bot includes error handling for:

- API rate limits
- Network issues
- Invalid wallet addresses
- Transaction parsing errors
- Notification sending failures

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is licensed under the MIT License - see the LICENSE file for details.
