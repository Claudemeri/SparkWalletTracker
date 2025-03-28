# Solana Wallet Tracker Bot

A Telegram bot for tracking Solana wallet transactions and detecting multi-buy patterns.

## Features

- Track multiple Solana wallets
- Real-time transaction monitoring via Helius webhooks
- Multi-buy pattern detection
- Token tracking
- Activity summaries
- Customizable alerts

## Setup

1. Clone the repository:

```bash
git clone https://github.com/Claudemeri/SparkWalletTracker.git
cd SparkWalletTracker
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file with the following variables:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
SOLANA_RPC_URL=your_solana_rpc_url
HELIUS_WEBHOOK_SECRET=your_helius_webhook_secret
PORT=8080  # Optional, defaults to 8080
```

4. Set up Helius webhook:

   - Go to [Helius Dashboard](https://dev.helius.xyz/dashboard)
   - Create a new webhook
   - Set the webhook URL to your bot's URL + `/webhook` (e.g., `https://your-bot-url.com/webhook`)
   - Get the webhook secret and add it to your `.env` file
   - Configure the webhook to track transaction events

5. Run the bot:

```bash
python bot.py
```

## Usage

### Basic Commands

- `/start` - Start the bot and show the main menu
- `/menu` - Show the main menu
- `/summary` - Show activity summary for tracked wallets

### Menu Options

- 📊 Summary - View transaction summaries
- ➕ Add Wallet - Add a new wallet to track
- ➖ Remove Wallet - Remove a tracked wallet
- 📝 List Wallets - View all tracked wallets
- 🔍 Track Token - Add a new token to track
- 🔔 Toggle Alerts - Enable/disable transaction alerts

### Multi-Buy Detection

The bot automatically detects when multiple tracked wallets buy the same token within a short time period (default: 6 hours). When detected, it:

1. Sends notifications to all tracked wallets
2. Shows the total value of buys
3. Lists all wallets that participated
4. Offers options to track sells for the token

## Configuration

### Rate Limiting

The bot includes built-in rate limiting to prevent API throttling:

- Default delay between requests: 200ms
- Maximum retries: 3
- Retry delay: 1 second (exponential backoff)

### Multi-Buy Settings

You can adjust these settings in the `WalletTracker` class:

- `multi_buy_threshold`: Time window for multi-buy detection (default: 6 hours)
- `min_buys_for_alert`: Minimum number of wallets that need to buy (default: 2)

## Security

- Webhook signatures are verified using HMAC-SHA256
- All sensitive data is stored in environment variables
- Rate limiting prevents API abuse
- Input validation for all user commands

## Error Handling

The bot includes comprehensive error handling for:

- Invalid wallet addresses
- Network issues
- API rate limits
- Transaction parsing errors
- Webhook verification failures

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
