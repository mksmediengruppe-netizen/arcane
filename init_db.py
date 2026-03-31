"""
ARCANE Database Initialization
Creates all tables and the default admin user.
Run once: python init_db.py
"""

import asyncio
import os
import sys
import hashlib
import secrets

from dotenv import load_dotenv
load_dotenv()

from shared.models.database import Base, User, get_async_engine, get_session_factory, init_database
from config.settings import get_config


async def main():
    config = get_config()
    db_url = config.db.url
    print(f"Connecting to: {config.db.host}:{config.db.port}/{config.db.name}")

    # Create all tables
    await init_database(db_url)
    print("All tables created successfully!")

    # Create default admin user if not exists
    factory = get_session_factory(db_url)
    async with factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            import bcrypt
            password = os.getenv("ADMIN_PASSWORD", "arcane2026")
            password_hash = bcrypt.hashpw(
                password.encode(), bcrypt.gensalt()
            ).decode()

            admin = User(
                username="admin",
                email="admin@arcaneai.ru",
                password_hash=password_hash,
                role="admin",
                is_active=True,
                model_strategy="balance",
                budget_limit=100.0,
            )
            session.add(admin)
            await session.commit()
            print(f"Admin user created (username: admin, password: {password})")
        else:
            print("Admin user already exists, skipping.")

    print("\nDatabase initialization complete!")
    print("Tables created:")
    for table_name in sorted(Base.metadata.tables.keys()):
        print(f"  - {table_name}")


if __name__ == "__main__":
    asyncio.run(main())
