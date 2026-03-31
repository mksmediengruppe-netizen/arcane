# WordPress Setup and Configuration

## When to Use
This skill applies when the user requests WordPress installation, theme setup, plugin configuration, or WooCommerce.

## Best Practices
1. **Installation**: Use WP-CLI for automated setup: `wp core install`
2. **Security**: Change default admin username, use strong passwords, install Wordfence
3. **Performance**: Install Redis object cache, enable Gzip, use CDN
4. **Themes**: Use lightweight themes (GeneratePress, Astra) or custom theme
5. **Plugins**: Keep plugins minimal — each plugin adds load time
6. **Backups**: Set up automated daily backups with UpdraftPlus
7. **SSL**: Always configure HTTPS with Let's Encrypt

## Common Tasks
- Install WordPress via SSH: `wp core download && wp core install`
- Install plugin: `wp plugin install {name} --activate`
- Update all: `wp core update && wp plugin update --all`
- Database backup: `wp db export backup.sql`

## Deployment
1. Install LAMP/LEMP stack on VPS
2. Create MySQL database and user
3. Download and configure WordPress
4. Set up Nginx virtual host with PHP-FPM
5. Configure SSL certificate
