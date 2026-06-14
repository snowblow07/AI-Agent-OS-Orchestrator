import sqlite3

def initialize_database():
    conn = sqlite3.connect('data/agent_os_events.db')
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS execution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        intent_hash TEXT NOT NULL,
        parent_intent_hash TEXT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    print("SQLite ledger initialized.")

if __name__ == "__main__":
    initialize_database()