# Landing Page Creation

## When to Use
This skill applies when the user requests a landing page, website, homepage, or promotional page.

## Best Practices
1. **Mobile-first**: Always design for mobile first, then scale up
2. **Performance**: Target < 3s load time. Use lazy loading for images
3. **Structure**: Hero → Features → Social Proof → CTA → Footer
4. **Typography**: Use 2 fonts max. Set hierarchy: h1 (48-64px), h2 (32-40px), body (16-18px)
5. **Colors**: Use 60-30-10 rule. Primary 60%, secondary 30%, accent 10%
6. **Whitespace**: Generous padding (80-120px between sections)
7. **CTA**: One primary CTA per viewport. Use contrasting color
8. **Images**: Use real photography or high-quality illustrations. Never use placeholder images
9. **Animations**: Subtle entrance animations (fade-in, slide-up). Use GSAP or CSS transitions
10. **SEO**: Include meta tags, Open Graph, semantic HTML5 tags

## File Structure
```
project/
├── index.html          # Single HTML file with embedded CSS/JS
├── assets/
│   ├── images/         # Optimized images (WebP preferred)
│   └── fonts/          # Custom fonts if needed
└── README.md           # Deployment instructions
```

## Common Mistakes to Avoid
- Don't use Lorem Ipsum — generate realistic content
- Don't hardcode pixel widths — use max-width + percentage
- Don't forget favicon and meta description
- Don't use more than 3 different font sizes
- Don't skip the mobile hamburger menu

## Deployment
Deploy via SSH to the user's VPS using Nginx or serve as static files.
