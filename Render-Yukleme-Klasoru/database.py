import os
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

load_dotenv()

class DBWrapper:
    """SQLite'daki conn.execute() mantığını psycopg2 ile simüle eden yardımcı sınıf."""
    def __init__(self, conn):
        self.conn = conn
    
    def execute(self, query, params=None):
        cur = self.conn.cursor(cursor_factory=DictCursor)
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur
    
    def commit(self):
        self.conn.commit()
        
    def close(self):
        self.conn.close()

def get_db_connection():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise ValueError("Lütfen .env dosyasına DATABASE_URL ekleyin.")
    
    conn = psycopg2.connect(db_url)
    return DBWrapper(conn)

def init_db():
    conn = get_db_connection()
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()
        conn.execute(schema)
    conn.commit()
    conn.close()
