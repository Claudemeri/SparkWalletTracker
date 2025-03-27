# Solana Wallet Tracker Bot

A Telegram bot that tracks Solana wallet transactions and provides notifications for multi-buy and multi-sell events.

## Features

- Track multiple Solana wallets
- Receive notifications for multi-buy events (when multiple tracked wallets buy the same token within 6 hours)
- Track token sales with options for multi-sell and individual sell notifications
- Add/remove wallets and toggle alerts through Telegram commands
- Persistent storage of wallet data

## Prerequisites

1. **Telegram Bot Token**

   - Open Telegram and search for [@BotFather](https://t.me/botfather)
   - Start a chat and send `/newbot`
   - Follow the prompts to create your bot
   - Save the API token provided by BotFather

2. **Solana RPC URL**

   - Option 1: Use a public RPC URL (not recommended for production)
     - Default: `https://api.mainnet-beta.solana.com`
   - Option 2: Get a dedicated RPC URL (recommended)
     - Sign up for [QuickNode](https://www.quicknode.com/) or [Alchemy](https://www.alchemy.com/)
     - Create a new Solana endpoint
     - Copy the HTTP endpoint URL

3. **Replit Account**

   - Go to [replit.com](https://replit.com)
   - Sign up for a free account
   - Verify your email address

4. **UptimeRobot Account**
   - Go to [uptimerobot.com](https://uptimerobot.com)
   - Sign up for a free account
   - Verify your email address

## Detailed Setup Instructions

### 1. Deploy on Replit

#### Step 1: Create New Repl

1. Go to [replit.com](https://replit.com)
2. Click the "+ Create" button
3. Select "Import from GitHub"
4. Enter this repository's URL
5. Choose "Python" as the language
6. Click "Import from GitHub"

#### Step 2: Configure Environment Variables

1. In your Repl, click on "Tools" in the left sidebar
2. Select "Secrets"
3. Add the following environment variables:
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   SOLANA_RPC_URL=your_solana_rpc_url_here
   PORT=8080
   ```
4. Click "Add Secret" for each variable
5. Make sure to replace the placeholder values with your actual credentials

#### Step 3: Install Dependencies

1. Open the Repl's shell (bottom panel)
2. Run the following command:
   ```bash
   pip install -r requirements.txt
   ```
3. Wait for the installation to complete

#### Step 4: Start the Bot

1. Click the "Run" button at the top of the Repl
2. Wait for the bot to start
3. You should see messages indicating:
   - "Web server started on port 8080"
   - "Bot started successfully"

#### Step 5: Get Your Repl's URL

1. Click the "Open in new tab" button (looks like a box with an arrow)
2. Copy the URL from your browser
3. The URL should look like: `https://your-repl-name.your-username.repl.co`
4. Save this URL for the UptimeRobot setup

### 2. Configure UptimeRobot

#### Step 1: Create New Monitor

1. Log in to your UptimeRobot dashboard
2. Click "Add New Monitor"
3. Select "HTTP(s)" as the monitor type
4. Click "Next"

#### Step 2: Configure Monitor Settings

1. **Basic Settings**

   - Friendly Name: "Solana Wallet Tracker"
   - URL: Paste your Repl's URL from Step 5 above
   - Monitoring Interval: 5 minutes
   - Timeout: 30 seconds
   - Alert When: Down

2. **Advanced Settings**

   - Keyword: "Bot is running!"
   - Port: 443
   - HTTP Method: GET
   - HTTP Headers: Leave empty
   - HTTP Username: Leave empty
   - HTTP Password: Leave empty
   - HTTP Post Data: Leave empty

3. **Alert Settings**

   - Click "Add Alert Contact"
   - Choose your preferred notification method:
     - Email: Enter your email address
     - SMS: Enter your phone number
     - Webhook: Enter your webhook URL
   - Set alert when: Down
   - Set alert after: 1 failure
   - Set alert every: 5 minutes

4. **Click "Create Monitor"**

#### Step 3: Verify Monitor

1. Wait for the first check (usually within 5 minutes)
2. Check the monitor status:
   - Green: Bot is running
   - Red: Bot is down
3. Test notifications by clicking "Test" in the monitor settings

### 3. Test the Bot

#### Step 1: Start Chat with Bot

1. Open Telegram
2. Search for your bot's username
3. Click "Start" or send `/start`
4. You should see the welcome message with buttons

#### Step 2: Add Test Wallet

1. Click "Add Wallet" button
2. Send the command in format:
   ```
   /addwallet <wallet_address> <wallet_name>
   ```
3. Example:
   ```
   /addwallet 5ZWj7a1f8tWkjBESHKgrLmXshuXxqeY9SYcfbshpAqPG TestWallet
   ```

#### Step 3: Verify Notifications

1. Wait for transactions to be detected
2. You should receive notifications for:
   - Multi-buy events
   - Option to track sells
   - Wallet updates

## Troubleshooting Guide

### Common Issues and Solutions

1. **Bot Not Responding**

   - Check Replit console for errors
   - Verify environment variables are set correctly
   - Ensure bot token is valid
   - Check UptimeRobot status

2. **Transactions Not Detected**

   - Verify wallet address format
   - Check RPC URL status
   - Ensure sufficient RPC credits
   - Verify transaction history exists

3. **Notifications Not Working**

   - Check if bot is blocked
   - Verify chat is started
   - Check alert settings
   - Ensure bot has message permissions

4. **Repl Sleeping Issues**
   - Verify UptimeRobot is pinging correctly
   - Check Repl's URL is accessible
   - Ensure web server is running
   - Consider upgrading to Hacker plan

### Monitoring and Maintenance

1. **Regular Checks**

   - Monitor UptimeRobot dashboard daily
   - Check Replit console for errors
   - Verify bot responses
   - Test notifications periodically

2. **Performance Optimization**
   - Monitor RPC usage
   - Check transaction processing speed
   - Verify data storage size
   - Optimize if needed

## Support

If you encounter any issues:

1. Check the troubleshooting guide
2. Review the error logs in Replit console
3. Check UptimeRobot status
4. Contact support if issues persist

## Contributing

Feel free to submit issues and enhancement requests!
