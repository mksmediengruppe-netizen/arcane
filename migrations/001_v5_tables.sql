-- ARCANE v5 Migration: interrupted_tasks, user_preferences, telegram_chat_id
-- Safe: uses IF NOT EXISTS / IF NOT COLUMN to avoid breaking existing data
-- Run: psql -U arcane -d arcane -f 001_v5_tables.sql

BEGIN;

-- 1. Table: interrupted_tasks — stores serialized agent state on stop
CREATE TABLE IF NOT EXISTS interrupted_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_state JSONB NOT NULL,
    -- agent_state contains: messages, iteration, artifacts, current_phase, consecutive_errors
    messages_snapshot JSONB,
    -- full _messages array for conversation continuity
    iteration INTEGER DEFAULT 0,
    total_cost FLOAT DEFAULT 0.0,
    budget_remaining FLOAT DEFAULT 0.0,
    reason VARCHAR(50) DEFAULT 'user_stop',
    -- reason: user_stop, budget_exceeded, error, timeout
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '7 days'),
    resumed_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_interrupted_tasks_chat_id ON interrupted_tasks(chat_id);
CREATE INDEX IF NOT EXISTS idx_interrupted_tasks_user_id ON interrupted_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_interrupted_tasks_active ON interrupted_tasks(is_active) WHERE is_active = TRUE;

-- 2. Table: user_preferences — auto-extracted user preferences from conversations
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,
    -- categories: language, coding_style, framework, design, communication, tools
    key VARCHAR(255) NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    -- 0.0 = guessed, 1.0 = explicitly stated by user
    source VARCHAR(50) DEFAULT 'auto',
    -- source: auto (extracted from chat), manual (set by user), system
    source_chat_id UUID,
    times_confirmed INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, category, key)
);

CREATE INDEX IF NOT EXISTS idx_user_prefs_user_id ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_prefs_category ON user_preferences(user_id, category);

-- 3. Add telegram_chat_id column to users table (for notifications)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'telegram_chat_id'
    ) THEN
        ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(100);
    END IF;
END $$;

-- 4. Add notification_settings JSONB column to users table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'notification_settings'
    ) THEN
        ALTER TABLE users ADD COLUMN notification_settings JSONB DEFAULT '{"telegram_enabled": false, "notify_on_complete": true, "notify_on_error": true}'::jsonb;
    END IF;
END $$;

-- 5. Add scratchpad column to chats table (for Scratchpad persistence)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chats' AND column_name = 'scratchpad'
    ) THEN
        ALTER TABLE chats ADD COLUMN scratchpad JSONB;
    END IF;
END $$;

COMMIT;
