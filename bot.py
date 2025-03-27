import os
import json
import asyncio
import base58
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.message import Message
from aiohttp import web

# Load environment variables
load_dotenv()

# Initialize Solana client
solana_client = AsyncClient(os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com'))

# Store wallet data
WALLETS_FILE = 'wallets.json'
TRACKED_TOKENS_FILE = 'tracked_tokens.json'
TRANSACTIONS_FILE = 'transactions.json'

# Known DEX program IDs
JUPITER_PROGRAM_ID = "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB"
RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# Web server setup
app = web.Application()
routes = web.RouteTableDef()

@routes.get('/')
async def health_check(request):
    return web.Response(text="Bot is running!")

class Transaction:
    def __init__(self, signature: str, timestamp: int, token_address: str, amount: float, price: float, is_buy: bool):
        self.signature = signature
        self.timestamp = timestamp
        self.token_address = token_address
        self.amount = amount
        self.price = price
        self.is_buy = is_buy
        self.total_value = amount * price

class WalletTracker:
    def __init__(self):
        self.wallets = self.load_wallets()
        self.tracked_tokens = self.load_tracked_tokens()
        self.transactions = self.load_transactions()
        self.alerts_enabled = True
        self.multi_buy_threshold = 6  # hours
        self.min_buys_for_alert = 2   # minimum number of wallets that need to buy

    def load_wallets(self):
        if os.path.exists(WALLETS_FILE):
            with open(WALLETS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def load_tracked_tokens(self):
        if os.path.exists(TRACKED_TOKENS_FILE):
            with open(TRACKED_TOKENS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def load_transactions(self):
        if os.path.exists(TRANSACTIONS_FILE):
            with open(TRANSACTIONS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def save_wallets(self):
        with open(WALLETS_FILE, 'w') as f:
            json.dump(self.wallets, f)

    def save_tracked_tokens(self):
        with open(TRACKED_TOKENS_FILE, 'w') as f:
            json.dump(self.tracked_tokens, f)

    def save_transactions(self):
        with open(TRANSACTIONS_FILE, 'w') as f:
            json.dump(self.transactions, f)

    def add_wallet(self, address, name):
        self.wallets[address] = {
            'name': name,
            'added_at': datetime.now().isoformat()
        }
        self.save_wallets()

    def remove_wallet(self, address):
        if address in self.wallets:
            del self.wallets[address]
            self.save_wallets()
            return True
        return False

    def get_wallet_name(self, address):
        return self.wallets.get(address, {}).get('name', address)

    def add_tracked_token(self, token_address, wallets):
        self.tracked_tokens[token_address] = {
            'wallets': wallets,
            'added_at': datetime.now().isoformat(),
            'multi_buy_detected': False
        }
        self.save_tracked_tokens()

    def remove_tracked_token(self, token_address):
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
            self.save_tracked_tokens()
            return True
        return False

    def add_transaction(self, wallet_address: str, transaction: Transaction):
        if wallet_address not in self.transactions:
            self.transactions[wallet_address] = []
        self.transactions[wallet_address].append({
            'signature': transaction.signature,
            'timestamp': transaction.timestamp,
            'token_address': transaction.token_address,
            'amount': transaction.amount,
            'price': transaction.price,
            'is_buy': transaction.is_buy,
            'total_value': transaction.total_value
        })
        self.save_transactions()

    def get_recent_transactions(self, wallet_address: str, hours: int = 6) -> List[Transaction]:
        if wallet_address not in self.transactions:
            return []
        
        cutoff_time = int((datetime.now() - timedelta(hours=hours)).timestamp())
        return [
            Transaction(**tx) for tx in self.transactions[wallet_address]
            if tx['timestamp'] >= cutoff_time
        ]

    def detect_multi_buys(self, token_address: str) -> Optional[Dict]:
        if token_address not in self.tracked_tokens:
            return None

        tracked_wallets = self.tracked_tokens[token_address]['wallets']
        recent_buys = {}

        for wallet in tracked_wallets:
            transactions = self.get_recent_transactions(wallet)
            for tx in transactions:
                if tx.token_address == token_address and tx.is_buy:
                    if wallet not in recent_buys:
                        recent_buys[wallet] = []
                    recent_buys[wallet].append(tx)

        if len(recent_buys) >= self.min_buys_for_alert:
            total_value = sum(
                sum(tx.total_value for tx in wallet_txs)
                for wallet_txs in recent_buys.values()
            )
            return {
                'token_address': token_address,
                'wallets': recent_buys,
                'total_value': total_value
            }
        return None

# Initialize wallet tracker
wallet_tracker = WalletTracker()

def start(update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Add Wallet", callback_data='add_wallet')],
        [InlineKeyboardButton("Remove Wallet", callback_data='remove_wallet')],
        [InlineKeyboardButton("List Wallets", callback_data='list_wallets')],
        [InlineKeyboardButton("Toggle Alerts", callback_data='toggle_alerts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        'Welcome to Solana Wallet Tracker! Choose an option:',
        reply_markup=reply_markup
    )

def button_handler(update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'add_wallet':
        query.message.reply_text(
            'Please send the wallet address and name in format:\n/addwallet <address> <name>'
        )
    elif query.data == 'remove_wallet':
        query.message.reply_text(
            'Please send the wallet address to remove:\n/removewallet <address>'
        )
    elif query.data == 'list_wallets':
        if not wallet_tracker.wallets:
            query.message.reply_text('No wallets are being tracked.')
        else:
            wallet_list = '\n'.join([f"{name} ({addr})" for addr, name in wallet_tracker.wallets.items()])
            query.message.reply_text(f'Tracked Wallets:\n{wallet_list}')
    elif query.data == 'toggle_alerts':
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        query.message.reply_text(f'Alerts have been {status}')
    elif query.data.startswith('track_sells_'):
        token_address = query.data.replace('track_sells_', '')
        handle_track_sells(update, context, token_address)

def add_wallet(update, context: CallbackContext):
    try:
        address, name = context.args
        wallet_tracker.add_wallet(address, name)
        update.message.reply_text(f'Added wallet {name} ({address})')
    except ValueError:
        update.message.reply_text('Please provide both address and name:\n/addwallet <address> <name>')

def remove_wallet(update, context: CallbackContext):
    try:
        address = context.args[0]
        if wallet_tracker.remove_wallet(address):
            update.message.reply_text(f'Removed wallet {address}')
        else:
            update.message.reply_text('Wallet not found')
    except IndexError:
        update.message.reply_text('Please provide a wallet address:\n/removewallet <address>')

def track_token(update, context: CallbackContext):
    try:
        token_address = context.args[0]
        wallet_tracker.add_tracked_token(token_address, list(wallet_tracker.wallets.keys()))
        update.message.reply_text(f'Now tracking token {token_address} for all wallets')
    except IndexError:
        update.message.reply_text('Please provide a token address:\n/tracktoken <address>')

def handle_track_sells(update, context: CallbackContext, token_address: str):
    keyboard = [
        [InlineKeyboardButton("Track Multi-Sells Only", callback_data=f'multi_sells_{token_address}')],
        [InlineKeyboardButton("Track All Sells", callback_data=f'all_sells_{token_address}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.message.reply_text(
        'Choose how to track sells:',
        reply_markup=reply_markup
    )

async def parse_transaction(signature: str, wallet_address: str) -> Optional[Transaction]:
    try:
        # Get transaction details
        tx_response = await solana_client.get_transaction(signature)
        if not tx_response.value:
            return None

        tx = tx_response.value
        timestamp = tx.block_time or int(datetime.now().timestamp())

        # Parse transaction instructions
        for ix in tx.transaction.message.instructions:
            program_id = str(ix.program_id)
            
            # Check if it's a Jupiter or Raydium swap
            if program_id in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                # Extract token addresses and amounts
                # This is a simplified version - you'll need to implement the actual parsing
                # based on the specific DEX program's instruction format
                token_address = str(ix.accounts[1])  # Example: token account
                amount = float(ix.data[1:9]) / 1e9  # Example: amount in lamports
                price = 1.0  # You'll need to implement price fetching
                
                # Determine if it's a buy or sell
                is_buy = str(ix.accounts[0]) == wallet_address
                
                return Transaction(
                    signature=signature,
                    timestamp=timestamp,
                    token_address=token_address,
                    amount=amount,
                    price=price,
                    is_buy=is_buy
                )
    except Exception as e:
        print(f"Error parsing transaction {signature}: {e}")
    return None

async def check_transactions():
    while True:
        if not wallet_tracker.alerts_enabled:
            await asyncio.sleep(60)
            continue

        for address in wallet_tracker.wallets:
            try:
                # Get recent transactions
                response = await solana_client.get_signatures_for_address(address)
                if response.value:
                    for sig in response.value:
                        # Parse and store transaction
                        tx = await parse_transaction(sig.signature, address)
                        if tx:
                            wallet_tracker.add_transaction(address, tx)
                            
                            # Check for multi-buys
                            multi_buy = wallet_tracker.detect_multi_buys(tx.token_address)
                            if multi_buy and not wallet_tracker.tracked_tokens[tx.token_address].get('multi_buy_detected'):
                                # Send multi-buy notification
                                message = f"🚨 Multi-Buy Alert!\n\n"
                                message += f"Token: {tx.token_address}\n"
                                message += f"Total Value: {multi_buy['total_value']:.2f} SOL\n\n"
                                message += "Wallets that bought:\n"
                                
                                for wallet, transactions in multi_buy['wallets'].items():
                                    wallet_name = wallet_tracker.get_wallet_name(wallet)
                                    total = sum(tx.total_value for tx in transactions)
                                    message += f"- {wallet_name}: {total:.2f} SOL\n"
                                
                                # Add tracking options
                                keyboard = [[
                                    InlineKeyboardButton(
                                        "Track Sells",
                                        callback_data=f'track_sells_{tx.token_address}'
                                    )
                                ]]
                                reply_markup = InlineKeyboardMarkup(keyboard)
                                
                                # Send notification to all tracked wallets
                                for wallet in wallet_tracker.wallets:
                                    try:
                                        await context.bot.send_message(
                                            chat_id=wallet,
                                            text=message,
                                            reply_markup=reply_markup
                                        )
                                    except Exception as e:
                                        print(f"Error sending notification to {wallet}: {e}")
                                
                                # Mark multi-buy as detected
                                wallet_tracker.tracked_tokens[tx.token_address]['multi_buy_detected'] = True
                                wallet_tracker.save_tracked_tokens()
                                
            except Exception as e:
                print(f"Error checking transactions for {address}: {e}")

        await asyncio.sleep(60)  # Check every minute

async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '8080')))
    await site.start()
    print(f"Web server started on port {os.getenv('PORT', '8080')}")

def main():
    # Create the Updater and pass it your bot's token
    updater = Updater(os.getenv('TELEGRAM_BOT_TOKEN'), use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("addwallet", add_wallet))
    dispatcher.add_handler(CommandHandler("removewallet", remove_wallet))
    dispatcher.add_handler(CommandHandler("tracktoken", track_token))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))

    # Add web routes
    app.add_routes(routes)

    # Start the web server
    asyncio.create_task(start_web_server())

    # Start the transaction checker
    asyncio.create_task(check_transactions())

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main() 