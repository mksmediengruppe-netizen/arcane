# Telegram Bot Development

## When to Use
This skill applies when the user requests a Telegram bot, chatbot, or Telegram integration.

## Best Practices
1. **Library**: Use python-telegram-bot v20+ (async) or aiogram v3
2. **Webhook vs Polling**: Use webhooks for production, polling for development
3. **Error handling**: Wrap all handlers in try/except with user-friendly error messages
4. **Rate limits**: Telegram allows max 30 messages/second to different chats
5. **Inline keyboards**: Use InlineKeyboardMarkup for interactive menus
6. **State management**: Use ConversationHandler for multi-step dialogs
7. **Database**: Store user data in PostgreSQL, not in memory

## File Structure
```
bot/
├── bot.py              # Main entry point
├── handlers/           # Command and message handlers
├── keyboards/          # Inline keyboard layouts
├── database/           # DB models and queries
├── config.py           # Settings and environment variables
└── requirements.txt    # Dependencies
```

## Deployment
1. Create bot via @BotFather, get token
2. Set webhook: `https://api.telegram.org/bot{TOKEN}/setWebhook?url={URL}`
3. Run with systemd service for persistence
4. Use environment variables for token storage
