"""
ARCANE Benchmark — Generate 5 landing pages to validate the scene pipeline.
Tests the full render path: SceneSpec -> component_retriever -> scene_assembler -> HTML.
No LLM calls needed — uses hardcoded scene plans to test template rendering.
"""
import asyncio
import os
import sys
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.scene_planner import SceneSpec, PagePlan
from workers.scene_assembler import assemble_page

OUTPUT_DIR = '/root/workspace/benchmarks'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Benchmark 1: Fitness Studio
FITNESS_PLAN = PagePlan(
    niche='fitness',
    niche_tags=['fitness', 'gym', 'training'],
    global_theme='light',
    scenes=[
        SceneSpec(
            scene_id='hero.cinematic_fullbleed',
            modifiers={'theme': 'light', 'layout': 'centered'},
            content={
                'headline': 'Transform Your Body, Transform Your Life',
                'subheadline': 'Elite personal training programs designed for real results. Join 2,000+ members who achieved their fitness goals.',
                'cta_primary_text': 'Start Free Trial',
                'cta_primary_href': '#pricing',
                'cta_secondary_text': 'View Programs',
                'cta_secondary_href': '#features',
                'bg_image': 'https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=1920',
            },
            order=0,
        ),
        SceneSpec(
            scene_id='proof.stats_bar',
            modifiers={'theme': 'light'},
            content={
                'stats': [
                    {'value': '2,000+', 'label': 'Active Members'},
                    {'value': '15+', 'label': 'Expert Trainers'},
                    {'value': '98%', 'label': 'Client Satisfaction'},
                    {'value': '50+', 'label': 'Weekly Classes'},
                ],
            },
            order=1,
        ),
        SceneSpec(
            scene_id='features.bento_premium',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Our Programs',
                'section_subtitle': 'Comprehensive fitness solutions for every goal',
                'features': [
                    {'icon': 'dumbbell', 'title': 'Strength Training', 'description': 'Build lean muscle with our progressive overload programs designed by certified strength coaches.'},
                    {'icon': 'heart', 'title': 'Cardio & HIIT', 'description': 'Burn fat and boost endurance with high-intensity interval training sessions.'},
                    {'icon': 'users', 'title': 'Group Classes', 'description': 'Yoga, Pilates, Boxing, and more — 50+ classes per week for all fitness levels.'},
                    {'icon': 'target', 'title': 'Personal Training', 'description': 'One-on-one coaching with customized nutrition plans and progress tracking.'},
                ],
            },
            order=2,
        ),
        SceneSpec(
            scene_id='testimonials.marquee',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'What Our Members Say',
                'testimonials': [
                    {'name': 'Sarah K.', 'role': 'Lost 30 lbs in 4 months', 'text': 'The trainers here are incredible. They pushed me beyond what I thought was possible. Best decision I ever made.', 'rating': 5},
                    {'name': 'Mike R.', 'role': 'Marathon Runner', 'text': 'From couch potato to marathon finisher in 8 months. The cardio program is world-class.', 'rating': 5},
                    {'name': 'Elena V.', 'role': 'Yoga Enthusiast', 'text': 'The yoga classes are transformative. I feel stronger, more flexible, and mentally clearer.', 'rating': 5},
                ],
            },
            order=3,
        ),
        SceneSpec(
            scene_id='pricing.cards',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Membership Plans',
                'section_subtitle': 'Choose the plan that fits your goals',
                'plans': [
                    {'name': 'Starter', 'price': '$29/mo', 'features': ['Gym access', 'Group classes', 'Locker room'], 'cta_text': 'Get Started', 'cta_href': '#contact'},
                    {'name': 'Pro', 'price': '$59/mo', 'features': ['Everything in Starter', '2 PT sessions/mo', 'Nutrition plan', 'Progress tracking'], 'cta_text': 'Go Pro', 'cta_href': '#contact', 'highlighted': True},
                    {'name': 'Elite', 'price': '$99/mo', 'features': ['Everything in Pro', 'Unlimited PT', 'Recovery suite', 'Priority booking'], 'cta_text': 'Go Elite', 'cta_href': '#contact'},
                ],
            },
            order=4,
        ),
        SceneSpec(
            scene_id='footer.authority_contact',
            modifiers={'theme': 'light'},
            content={
                'brand_name': 'FitForge Studio',
                'tagline': 'Transform Your Body, Transform Your Life',
                'address': '123 Fitness Ave, New York, NY 10001',
                'phone': '+1 (555) 123-4567',
                'email': 'hello@fitforge.com',
            },
            order=5,
        ),
    ],
)

# Benchmark 2: Law Firm
LEGAL_PLAN = PagePlan(
    niche='legal',
    niche_tags=['legal', 'lawyer', 'law firm'],
    global_theme='light',
    scenes=[
        SceneSpec(
            scene_id='hero.legal_authority',
            modifiers={'theme': 'light', 'layout': 'split'},
            content={
                'headline': 'Protecting Your Rights with Precision and Integrity',
                'subheadline': 'Over 25 years of experience in corporate law, litigation, and intellectual property. Trusted by Fortune 500 companies.',
                'cta_primary_text': 'Schedule Consultation',
                'cta_primary_href': '#contact',
                'cta_secondary_text': 'Our Practice Areas',
                'cta_secondary_href': '#features',
            },
            order=0,
        ),
        SceneSpec(
            scene_id='trust.authority_facts_rail',
            modifiers={'theme': 'light'},
            content={
                'facts': [
                    {'value': '25+', 'label': 'Years of Practice'},
                    {'value': '500+', 'label': 'Cases Won'},
                    {'value': '98%', 'label': 'Success Rate'},
                    {'value': '50+', 'label': 'Attorneys'},
                ],
            },
            order=1,
        ),
        SceneSpec(
            scene_id='features.process_timeline',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Our Legal Process',
                'section_subtitle': 'A structured approach to achieving the best outcome',
                'steps': [
                    {'number': '01', 'title': 'Initial Consultation', 'description': 'We listen to your case, assess the legal landscape, and provide an honest evaluation of your options.'},
                    {'number': '02', 'title': 'Strategy Development', 'description': 'Our team crafts a tailored legal strategy designed to maximize your chances of a favorable outcome.'},
                    {'number': '03', 'title': 'Execution and Advocacy', 'description': 'We aggressively pursue your interests through negotiation, mediation, or litigation as needed.'},
                    {'number': '04', 'title': 'Resolution and Follow-up', 'description': 'We ensure the resolution is properly implemented and provide ongoing counsel as needed.'},
                ],
            },
            order=2,
        ),
        SceneSpec(
            scene_id='trust.case_grid',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Notable Cases',
                'cases': [
                    {'title': 'Corporate Merger Defense', 'category': 'Corporate Law', 'result': '$2.3B merger successfully defended'},
                    {'title': 'IP Patent Dispute', 'category': 'Intellectual Property', 'result': 'Full patent rights restored'},
                    {'title': 'Class Action Settlement', 'category': 'Litigation', 'result': '$45M settlement for 10,000 plaintiffs'},
                ],
            },
            order=3,
        ),
        SceneSpec(
            scene_id='testimonials.quote_wall',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Client Testimonials',
                'testimonials': [
                    {'name': 'James W.', 'role': 'CEO, TechCorp', 'text': 'Their attention to detail and strategic thinking saved our company millions. Absolutely top-tier legal representation.'},
                    {'name': 'Maria L.', 'role': 'Founder, InnovateLab', 'text': 'They made a complex IP dispute feel manageable. Professional, responsive, and incredibly knowledgeable.'},
                ],
            },
            order=4,
        ),
        SceneSpec(
            scene_id='footer.authority_contact',
            modifiers={'theme': 'light'},
            content={
                'brand_name': 'Sterling and Associates',
                'tagline': 'Precision. Integrity. Results.',
                'address': '500 Park Avenue, Suite 2100, New York, NY 10022',
                'phone': '+1 (212) 555-0199',
                'email': 'contact@sterlinglaw.com',
            },
            order=5,
        ),
    ],
)

# Benchmark 3: Luxury Spa
LUXURY_SPA_PLAN = PagePlan(
    niche='luxury_service',
    niche_tags=['luxury', 'spa', 'beauty', 'premium'],
    global_theme='light',
    scenes=[
        SceneSpec(
            scene_id='hero.editorial_split',
            modifiers={'theme': 'light', 'layout': 'split'},
            content={
                'headline': 'Where Luxury Meets Serenity',
                'subheadline': 'An exclusive sanctuary of wellness and beauty in the heart of Manhattan. Indulge in world-class treatments curated for the discerning.',
                'cta_primary_text': 'Book Your Experience',
                'cta_primary_href': '#pricing',
                'cta_secondary_text': 'Explore Treatments',
                'cta_secondary_href': '#features',
                'image': 'https://images.unsplash.com/photo-1540555700478-4be289fbec6d?w=800',
            },
            order=0,
        ),
        SceneSpec(
            scene_id='features.editorial_cards',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Signature Treatments',
                'section_subtitle': 'Each experience is crafted with precision and care',
                'features': [
                    {'icon': 'sparkles', 'title': 'Diamond Facial', 'description': 'A luxurious facial using diamond-infused serums and LED therapy for radiant, youthful skin.'},
                    {'icon': 'droplets', 'title': 'Hydrotherapy Suite', 'description': 'Immerse yourself in our private hydrotherapy pools with mineral-rich waters and aromatherapy.'},
                    {'icon': 'hand', 'title': 'Deep Tissue Massage', 'description': 'Expert therapists use ancient techniques combined with modern science for total body restoration.'},
                    {'icon': 'leaf', 'title': 'Organic Body Wrap', 'description': 'Detoxify and rejuvenate with our signature organic body wrap using sustainably sourced ingredients.'},
                ],
            },
            order=1,
        ),
        SceneSpec(
            scene_id='gallery.masonry_grid',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Our Sanctuary',
                'images': [
                    {'src': 'https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=600', 'alt': 'Spa treatment room'},
                    {'src': 'https://images.unsplash.com/photo-1600334089648-b0d9d3028eb2?w=600', 'alt': 'Relaxation lounge'},
                    {'src': 'https://images.unsplash.com/photo-1507652313519-d4e9174996dd?w=600', 'alt': 'Hydrotherapy pool'},
                    {'src': 'https://images.unsplash.com/photo-1519823551278-64ac92734fb1?w=600', 'alt': 'Meditation garden'},
                ],
            },
            order=2,
        ),
        SceneSpec(
            scene_id='parallax.quote',
            modifiers={'theme': 'light'},
            content={
                'quote': 'True luxury is not about excess. It is about the art of feeling extraordinary in every moment.',
                'author': 'Elena Marchetti, Founder',
            },
            order=3,
        ),
        SceneSpec(
            scene_id='pricing.cards',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Membership Tiers',
                'section_subtitle': 'Exclusive access to our world of wellness',
                'plans': [
                    {'name': 'Serenity', 'price': '$199/mo', 'features': ['2 treatments/month', 'Relaxation lounge', 'Herbal tea bar'], 'cta_text': 'Join', 'cta_href': '#contact'},
                    {'name': 'Radiance', 'price': '$399/mo', 'features': ['5 treatments/month', 'Hydrotherapy access', 'Priority booking', 'Guest passes'], 'cta_text': 'Join', 'cta_href': '#contact', 'highlighted': True},
                    {'name': 'Opulence', 'price': '$799/mo', 'features': ['Unlimited treatments', 'Private suite', 'Personal concierge', 'Exclusive events'], 'cta_text': 'Join', 'cta_href': '#contact'},
                ],
            },
            order=4,
        ),
        SceneSpec(
            scene_id='footer.authority_contact',
            modifiers={'theme': 'light'},
            content={
                'brand_name': 'Aurum Spa and Wellness',
                'tagline': 'Where Luxury Meets Serenity',
                'address': '888 Fifth Avenue, New York, NY 10065',
                'phone': '+1 (212) 555-0888',
                'email': 'reservations@aurumspa.com',
            },
            order=5,
        ),
    ],
)

# Benchmark 4: SaaS / Tech Product
SAAS_PLAN = PagePlan(
    niche='saas',
    niche_tags=['saas', 'software', 'tech', 'platform'],
    global_theme='light',
    scenes=[
        SceneSpec(
            scene_id='hero.product_showcase',
            modifiers={'theme': 'light', 'layout': 'centered'},
            content={
                'headline': 'Ship Faster with AI-Powered DevOps',
                'subheadline': 'Automate deployments, monitor performance, and resolve incidents 10x faster. Trusted by 500+ engineering teams worldwide.',
                'cta_primary_text': 'Start Free Trial',
                'cta_primary_href': '#pricing',
                'cta_secondary_text': 'Watch Demo',
                'cta_secondary_href': '#features',
                'product_image': 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1200',
            },
            order=0,
        ),
        SceneSpec(
            scene_id='proof.stats_bar',
            modifiers={'theme': 'light'},
            content={
                'stats': [
                    {'value': '500+', 'label': 'Engineering Teams'},
                    {'value': '99.99%', 'label': 'Uptime SLA'},
                    {'value': '10x', 'label': 'Faster Deployments'},
                    {'value': '60%', 'label': 'Cost Reduction'},
                ],
            },
            order=1,
        ),
        SceneSpec(
            scene_id='features.bento_premium',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Platform Features',
                'section_subtitle': 'Everything you need to ship with confidence',
                'features': [
                    {'icon': 'rocket', 'title': 'Automated CI/CD', 'description': 'Zero-config pipelines that deploy your code in seconds, not hours. Supports all major frameworks.'},
                    {'icon': 'shield', 'title': 'Security Scanning', 'description': 'Continuous vulnerability scanning with automated remediation suggestions and compliance reports.'},
                    {'icon': 'activity', 'title': 'Real-time Monitoring', 'description': 'Full-stack observability with custom dashboards, alerting, and AI-powered anomaly detection.'},
                    {'icon': 'git-branch', 'title': 'GitOps Workflows', 'description': 'Declarative infrastructure management with automatic drift detection and rollback capabilities.'},
                ],
            },
            order=2,
        ),
        SceneSpec(
            scene_id='trust.comparison_block',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Why Teams Switch to Us',
                'before_label': 'Before',
                'after_label': 'With DevShip',
                'comparisons': [
                    {'before': 'Manual deployments taking hours', 'after': 'Automated deploys in under 60 seconds'},
                    {'before': 'Blind spots in production', 'after': 'Full observability with AI insights'},
                    {'before': 'Security as an afterthought', 'after': 'Security baked into every pipeline'},
                    {'before': 'Fragmented toolchain', 'after': 'Single platform, zero context switching'},
                ],
            },
            order=3,
        ),
        SceneSpec(
            scene_id='pricing.cards',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Simple, Transparent Pricing',
                'section_subtitle': 'No hidden fees. Cancel anytime.',
                'plans': [
                    {'name': 'Starter', 'price': '$49/mo', 'features': ['5 projects', '1,000 deploys/mo', 'Basic monitoring', 'Community support'], 'cta_text': 'Start Free', 'cta_href': '#contact'},
                    {'name': 'Team', 'price': '$199/mo', 'features': ['Unlimited projects', '10,000 deploys/mo', 'Advanced monitoring', 'Priority support', 'SSO'], 'cta_text': 'Start Free', 'cta_href': '#contact', 'highlighted': True},
                    {'name': 'Enterprise', 'price': 'Custom', 'features': ['Unlimited everything', 'Dedicated support', 'Custom SLA', 'On-premise option', 'SOC2 compliance'], 'cta_text': 'Contact Sales', 'cta_href': '#contact'},
                ],
            },
            order=4,
        ),
        SceneSpec(
            scene_id='footer.authority_contact',
            modifiers={'theme': 'light'},
            content={
                'brand_name': 'DevShip',
                'tagline': 'Ship Faster. Sleep Better.',
                'email': 'hello@devship.io',
            },
            order=5,
        ),
    ],
)

# Benchmark 5: Restaurant
RESTAURANT_PLAN = PagePlan(
    niche='restaurant',
    niche_tags=['restaurant', 'food', 'dining'],
    global_theme='light',
    scenes=[
        SceneSpec(
            scene_id='hero.cinematic_fullbleed',
            modifiers={'theme': 'light', 'layout': 'centered'},
            content={
                'headline': 'A Culinary Journey Through Tuscany',
                'subheadline': 'Authentic Italian cuisine crafted with passion, using the finest locally-sourced ingredients. Reserve your table for an unforgettable dining experience.',
                'cta_primary_text': 'Reserve a Table',
                'cta_primary_href': '#contact',
                'cta_secondary_text': 'View Menu',
                'cta_secondary_href': '#features',
                'bg_image': 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1920',
            },
            order=0,
        ),
        SceneSpec(
            scene_id='about.split_image',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Our Story',
                'text': 'Founded in 2010 by Chef Marco Bellini, La Toscana brings the authentic flavors of Tuscany to New York. Every dish tells a story of tradition, passion, and the finest ingredients sourced directly from Italian farms.',
                'image': 'https://images.unsplash.com/photo-1556910103-1c02745aae4d?w=800',
                'image_alt': 'Chef Marco Bellini in the kitchen',
            },
            order=1,
        ),
        SceneSpec(
            scene_id='features.editorial_cards',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'The Menu',
                'section_subtitle': 'Seasonal dishes crafted with love',
                'features': [
                    {'icon': 'utensils', 'title': 'Antipasti', 'description': 'Burrata with heirloom tomatoes, truffle arancini, and our signature carpaccio with aged Parmigiano.'},
                    {'icon': 'flame', 'title': 'Primi Piatti', 'description': 'Handmade pappardelle with wild boar ragu, risotto ai funghi porcini, and lobster linguine.'},
                    {'icon': 'beef', 'title': 'Secondi', 'description': 'Bistecca alla Fiorentina, pan-seared branzino, and ossobuco with saffron gremolata.'},
                    {'icon': 'cake', 'title': 'Dolci', 'description': 'Classic tiramisu, panna cotta with seasonal berries, and our famous chocolate fondant.'},
                ],
            },
            order=2,
        ),
        SceneSpec(
            scene_id='testimonials.marquee',
            modifiers={'theme': 'light'},
            content={
                'section_title': 'Guest Reviews',
                'testimonials': [
                    {'name': 'The New York Times', 'role': 'Restaurant Review', 'text': 'La Toscana delivers an authentic Italian experience that rivals the best trattorias in Florence. A must-visit.', 'rating': 5},
                    {'name': 'Amanda C.', 'role': 'Regular Guest', 'text': 'The pappardelle is the best I have ever had outside of Italy. The ambiance is warm and inviting.', 'rating': 5},
                    {'name': 'David M.', 'role': 'Food Blogger', 'text': 'Chef Bellini is a true artist. Every dish is a masterpiece of flavor and presentation.', 'rating': 5},
                ],
            },
            order=3,
        ),
        SceneSpec(
            scene_id='cta.executive_split',
            modifiers={'theme': 'light'},
            content={
                'headline': 'Reserve Your Table Tonight',
                'text': 'Experience the magic of authentic Tuscan cuisine. Private dining rooms available for special occasions.',
                'cta_primary_text': 'Make a Reservation',
                'cta_primary_href': '#contact',
                'cta_secondary_text': 'Call Us: (212) 555-0177',
                'cta_secondary_href': 'tel:+12125550177',
            },
            order=4,
        ),
        SceneSpec(
            scene_id='footer.authority_contact',
            modifiers={'theme': 'light'},
            content={
                'brand_name': 'La Toscana',
                'tagline': 'Authentic Italian Cuisine Since 2010',
                'address': '245 Mulberry Street, New York, NY 10012',
                'phone': '+1 (212) 555-0177',
                'email': 'reservations@latoscana.nyc',
            },
            order=5,
        ),
    ],
)

# Run all benchmarks
BENCHMARKS = [
    ('01_fitness_studio', FITNESS_PLAN),
    ('02_law_firm', LEGAL_PLAN),
    ('03_luxury_spa', LUXURY_SPA_PLAN),
    ('04_saas_devops', SAAS_PLAN),
    ('05_restaurant', RESTAURANT_PLAN),
]

async def main():
    results = []
    for name, plan in BENCHMARKS:
        print(f'\n{"="*60}')
        print(f'Generating: {name} ({len(plan.scenes)} scenes)')
        print(f'{"="*60}')
        try:
            html = await assemble_page(plan, fetch_images=False, lang='en')
            output_path = os.path.join(OUTPUT_DIR, f'{name}.html')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)
            # Validate
            issues = []
            unresolved = re.findall(r'\{\{[A-Z_]+\}\}', html)
            if unresolved:
                issues.append(f'Unresolved placeholders: {set(unresolved)}')
            if '<i data-lucide=' not in html and '<svg' not in html:
                issues.append('No icons found')
            if 'id="' not in html:
                issues.append('No section IDs')
            if len(html) < 5000:
                issues.append(f'Suspiciously short HTML: {len(html)} chars')

            status = 'PASS' if not issues else f'WARN: {"; ".join(issues)}'
            results.append((name, len(html), len(plan.scenes), status))
            print(f'  -> {output_path} ({len(html):,} chars) [{status}]')
        except Exception as e:
            results.append((name, 0, len(plan.scenes), f'FAIL: {e}'))
            print(f'  -> FAILED: {e}')
            import traceback
            traceback.print_exc()

    print(f'\n{"="*60}')
    print('BENCHMARK RESULTS')
    print(f'{"="*60}')
    print(f'{"Name":<25} {"Size":>10} {"Scenes":>8} Status')
    print('-' * 70)
    for name, size, scenes, status in results:
        print(f'{name:<25} {size:>10,} {scenes:>8} {status}')
    
    passed = sum(1 for _, _, _, s in results if s == 'PASS')
    total = len(results)
    warns = sum(1 for _, _, _, s in results if s.startswith('WARN'))
    fails = sum(1 for _, _, _, s in results if s.startswith('FAIL'))
    print(f'\n{passed} passed, {warns} warnings, {fails} failed out of {total} benchmarks')

asyncio.run(main())
