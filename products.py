import sqlite3
conn = sqlite3.connect('ecommerce.db')
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS products (name TEXT, price INTEGER, image TEXT, category TEXT)")
cur.execute("DELETE FROM products")
products = [("iPhone 15",79999,"iphone.jpg","Mobile"),("Samsung S24",69999,"samsung.jpg","Mobile"),("Nike Air",8999,"nike.jpg","Shoes"),("MacBook Air",99999,"macbook.jpg","Laptop"),("Apple Watch",39999,"watch.jpg","Watch")]
for p in products:
    cur.execute("INSERT INTO products VALUES (?,?,?,?)", p)
conn.commit()
conn.close()
print("DONE! 5 Products Added")