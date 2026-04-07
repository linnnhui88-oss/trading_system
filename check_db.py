import sqlite3
import sys

conn = sqlite3.connect('data/trade_history.db')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', [t[0] for t in cursor.fetchall()])

cursor.execute('SELECT COUNT(*) FROM trades')
print('Trades count:', cursor.fetchone()[0])

cursor.execute('SELECT COUNT(*) FROM signals')
print('Signals count:', cursor.fetchone()[0])

conn.close()
