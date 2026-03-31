# n8n Workflow Automation

## When to Use
This skill applies when the user requests n8n workflow creation, webhook setup, or automation between services.

## Best Practices
1. **Error handling**: Always add an Error Trigger node at the start
2. **Naming**: Use descriptive node names (not "HTTP Request 1")
3. **Credentials**: Never hardcode API keys — use n8n credentials store
4. **Testing**: Test each node individually before connecting the full workflow
5. **Webhooks**: Use production webhook URLs, not test URLs, for deployment
6. **Rate limiting**: Add Wait nodes between API calls to avoid rate limits
7. **Logging**: Add Set nodes to log key data points for debugging

## Common Integrations
- Telegram Bot → n8n Webhook → Process → Response
- CRM (Bitrix24/HubSpot) → n8n → Database/Notification
- Form submission → n8n → Email + CRM + Slack
- Scheduled trigger → Data fetch → Transform → Report

## Workflow Export Format
Export workflows as JSON and store in the project directory.

## Deployment
1. Access n8n at the configured URL (usually port 5678)
2. Import workflow JSON via n8n UI or API
3. Activate the workflow
4. Test with sample data
