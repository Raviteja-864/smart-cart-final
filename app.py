from functools import wraps
import os
import uuid
import random
from flask import Flask, render_template, request, redirect, session, flash, url_for, send_from_directory, jsonify
from flask_mail import Mail, Message
import bcrypt
import razorpay
from werkzeug.utils import secure_filename

import config
import db

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = config.SECRET_KEY

# Mail Configuration
app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
mail = Mail(app)

# Upload Folder Setup
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Database Schema & Seed Data
db.init_db()

# Initialize Razorpay Client
try:
    razorpay_client = razorpay.Client(auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET))
except Exception as e:
    print(f"Razorpay Client Init Warning: {e}")
    razorpay_client = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Decorators
def admin_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            flash("Please log in as Admin to access this page.", "warning")
            return redirect('/admin-login')
        return f(*args, **kwargs)
    return decorated

def user_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to continue.", "info")
            return redirect('/user-login')
        return f(*args, **kwargs)
    return decorated

# Context Processors for Templates
@app.context_processor
def inject_global_data():
    cart_count = 0
    if 'user_id' in session:
        try:
            conn = db.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT SUM(quantity) as count FROM cart WHERE user_id=%s", (session['user_id'],))
            row = cur.fetchone()
            cart_count = int(row['count']) if row and row.get('count') else 0
            cur.close()
            conn.close()
        except Exception as e:
            cart_count = 0
    return dict(
        cart_count=cart_count,
        user_name=session.get('user_name'),
        admin_name=session.get('admin_name'),
        razorpay_key_id=config.RAZORPAY_KEY_ID
    )

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==========================
# PUBLIC & HOME ROUTES
# ==========================
@app.route('/')
def home():
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY product_id DESC LIMIT 8")
    featured_products = cur.fetchall()
    
    cur.execute("SELECT DISTINCT category FROM products")
    categories = [r['category'] for r in cur.fetchall() if r.get('category')]
    
    cur.close()
    conn.close()
    return render_template("index.html", products=featured_products, categories=categories)

# ==========================
# ADMIN AUTH & MANAGEMENT
# ==========================
@app.route('/admin-signup', methods=['GET', 'POST'])
def admin_signup():
    if request.method == 'GET':
        return render_template("admin/admin_signup.html")
    
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()

    if not name or not email or not password:
        flash("All fields are required.", "danger")
        return redirect('/admin-signup')

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT admin_id FROM admin WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        flash("Admin email already exists. Please login.", "warning")
        return redirect('/admin-login')
    
    cur.close()
    conn.close()

    # Generate OTP
    otp = random.randint(100000, 999999)
    session['signup_name'] = name
    session['signup_email'] = email
    session['signup_password'] = password
    session['otp'] = otp

    # Try sending OTP email
    try:
        msg = Message("SmartCart Admin Verification OTP", sender=config.MAIL_USERNAME, recipients=[email])
        msg.body = f"Your verification OTP code for SmartCart Admin account is: {otp}"
        mail.send(msg)
        flash("Verification OTP sent to your email!", "info")
        return redirect('/verify-otp')
    except Exception as e:
        print(f"Mail Exception: {e}")
        # Direct registration fallback if mail sending fails (e.g. invalid SMTP creds)
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)", (name, email, hashed))
        conn.commit()
        cur.close()
        conn.close()
        flash("Admin account registered successfully! Please login.", "success")
        return redirect('/admin-login')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'signup_email' not in session:
        return redirect('/admin-signup')
    
    if request.method == 'GET':
        return render_template("admin/verify_otp.html")
    
    entered_otp = request.form.get('otp', '').strip()
    if str(session.get('otp')) != entered_otp:
        flash("Invalid OTP code. Please try again.", "danger")
        return redirect('/verify-otp')
    
    pwd = session.get('signup_password')
    hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
    
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)",
                (session['signup_name'], session['signup_email'], hashed))
    conn.commit()
    cur.close()
    conn.close()

    session.pop('otp', None)
    session.pop('signup_name', None)
    session.pop('signup_email', None)
    session.pop('signup_password', None)
    flash("OTP verified! Admin account created successfully.", "success")
    return redirect('/admin-login')

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        if 'admin_id' in session:
            return redirect('/admin-dashboard')
        return render_template("admin/admin_login.html")
    
    email = request.form.get('email', '').strip().lower()
    pwd = request.form.get('password', '').strip()

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin WHERE email=%s", (email,))
    admin = cur.fetchone()
    cur.close()
    conn.close()

    if not admin:
        flash("Admin account not found. Please sign up.", "danger")
        return redirect('/admin-login')
    
    try:
        is_valid = bcrypt.checkpw(pwd.encode(), admin['password'].encode())
    except Exception:
        is_valid = (pwd == admin['password'])

    if not is_valid:
        flash("Incorrect password. Please try again.", "danger")
        return redirect('/admin-login')
    
    session['admin_id'] = admin['admin_id']
    session['admin_name'] = admin['name']
    session['admin_email'] = admin['email']
    flash(f"Welcome back, {admin['name']}!", "success")
    return redirect('/admin-dashboard')

@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        new_pwd = request.form.get('new_password', '').strip()
        
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admin WHERE email=%s", (email,))
        admin = cur.fetchone()
        
        if admin:
            hashed = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt()).decode()
            cur.execute("UPDATE admin SET password=%s WHERE email=%s", (hashed, email))
            conn.commit()
            flash("Password reset successfully! Please login with your new password.", "success")
            cur.close()
            conn.close()
            return redirect('/admin-login')
        else:
            flash("Email address not found in admin database.", "danger")
        cur.close()
        conn.close()
    
    return render_template("admin/forgot_password.html")
@app.route('/forgot-password', methods=['GET', 'POST'])
def user_forgot_password():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        new_pwd = request.form.get('new_password','').strip()
        
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        
        if user:
            hashed = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt()).decode()
            cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
            conn.commit()
            flash("Password reset successfully! Please login with your new password.", "success")
            cur.close()
            conn.close()
            return redirect('/user-login')
        else:
            flash("Email not found", "danger")
            cur.close()
            conn.close()
    return render_template('user/forgot_password.html')

@app.route('/admin-dashboard')
@admin_login_required
def admin_dashboard():
    conn = db.get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as total FROM products")
    p_count = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) as total FROM orders")
    o_count = cur.fetchone()['total']

    cur.execute("SELECT SUM(total_amount) as total FROM orders WHERE payment_status='Paid' OR status!='Cancelled'")
    total_rev_row = cur.fetchone()
    total_revenue = total_rev_row['total'] if total_rev_row and total_rev_row.get('total') else 0.0

    cur.execute("SELECT COUNT(*) as total FROM orders WHERE status='Placed' OR status='Processing'")
    pending_orders = cur.fetchone()['total']

    cur.execute("SELECT * FROM products ORDER BY product_id DESC LIMIT 6")
    recent_products = cur.fetchall()

    cur.execute("""
        SELECT o.*, u.name as user_name, u.email as user_email 
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.user_id 
        ORDER BY o.order_id DESC LIMIT 8
    """)
    recent_orders = cur.fetchall()

    cur.close()
    conn.close()
    return render_template("admin/admin_dashboard.html",
                           product_count=p_count,
                           order_count=o_count,
                           total_revenue=total_revenue,
                           pending_orders=pending_orders,
                           products=recent_products,
                           recent_orders=recent_orders)

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_name', None)
    session.pop('admin_email', None)
    flash("Admin logged out successfully.", "info")
    return redirect('/admin-login')

@app.route('/admin/add-item', methods=['GET', 'POST'])
@app.route('/add-item', methods=['GET', 'POST'])
@admin_login_required
def add_item():
    if request.method == 'GET':
        return render_template('admin/add_item.html')
    
    name = request.form.get('name', '').strip()
    desc = request.form.get('description', '').strip()
    cat = request.form.get('category', '').strip()
    price = request.form.get('price', '').strip()
    original_price = request.form.get('original_price', '').strip() or price
    stock = request.form.get('stock_quantity', '50').strip()
    badge = request.form.get('badge', 'Popular').strip()
    image_url = request.form.get('image_url', '').strip()
    img_file = request.files.get('image')

    if not name or not desc or not cat or not price:
        flash("Product name, description, category, and price are required.", "danger")
        return redirect('/admin/add-item')

    final_image = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=800&q=80"
    
    if img_file and img_file.filename != '':
        if allowed_file(img_file.filename):
            fname = f"{uuid.uuid4().hex}_{secure_filename(img_file.filename)}"
            img_file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            final_image = fname
    elif image_url:
        final_image = image_url

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO products (name, description, category, price, original_price, stock_quantity, badge, image) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (name, desc, cat, float(price), float(original_price), int(stock), badge, final_image))
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Product '{name}' added successfully!", "success")
    return redirect('/admin/item-list')

@app.route('/admin/item-list')
@admin_login_required
def item_list():
    search = request.args.get('search', '').strip()
    cat_filter = request.args.get('category', '').strip()

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM products")
    categories = [c['category'] for c in cur.fetchall() if c.get('category')]

    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        query += " AND name LIKE %s"
        params.append(f"%{search}%")
    if cat_filter:
        query += " AND category = %s"
        params.append(cat_filter)
    
    query += " ORDER BY product_id DESC"
    cur.execute(query, params)
    products = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("admin/item_list.html", products=products, categories=categories, selected_category=cat_filter, search=search)

@app.route('/admin/view-item/<int:item_id>')
@admin_login_required
def view_item(item_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE product_id=%s", (item_id,))
    prod = cur.fetchone()
    cur.close()
    conn.close()
    if not prod:
        flash("Product not found.", "warning")
        return redirect('/admin/item-list')
    return render_template("admin/view_item.html", product=prod)

@app.route('/admin/update-item/<int:item_id>', methods=['GET', 'POST'])
@admin_login_required
def update_item_page(item_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE product_id=%s", (item_id,))
    prod = cur.fetchone()

    if not prod:
        cur.close()
        conn.close()
        flash("Product not found.", "warning")
        return redirect('/admin/item-list')

    if request.method == 'GET':
        cur.close()
        conn.close()
        return render_template("admin/update_item.html", product=prod)
    
    name = request.form.get('name', prod['name'])
    desc = request.form.get('description', prod['description'])
    cat = request.form.get('category', prod['category'])
    price = request.form.get('price', prod['price'])
    original_price = request.form.get('original_price', prod.get('original_price') or price)
    stock = request.form.get('stock_quantity', prod.get('stock_quantity') or 50)
    badge = request.form.get('badge', prod.get('badge') or 'Popular')
    image_url = request.form.get('image_url', '').strip()
    new_img = request.files.get('image')

    final_img = prod['image']
    if new_img and new_img.filename != "":
        if allowed_file(new_img.filename):
            fname = f"{uuid.uuid4().hex}_{secure_filename(new_img.filename)}"
            new_img.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            final_img = fname
    elif image_url:
        final_img = image_url

    cur.execute("""
        UPDATE products 
        SET name=%s, description=%s, category=%s, price=%s, original_price=%s, stock_quantity=%s, badge=%s, image=%s 
        WHERE product_id=%s
    """, (name, desc, cat, float(price), float(original_price), int(stock), badge, final_img, item_id))
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Product '{name}' updated successfully!", "success")
    return redirect('/admin/item-list')

@app.route('/admin/delete-item/<int:item_id>')
@admin_login_required
def delete_item(item_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT image FROM products WHERE product_id=%s", (item_id,))
    prod = cur.fetchone()
    
    if prod and prod['image'] and not prod['image'].startswith('http'):
        path = os.path.join(app.config['UPLOAD_FOLDER'], prod['image'])
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    cur.execute("DELETE FROM products WHERE product_id=%s", (item_id,))
    conn.commit()
    cur.close()
    conn.close()

    flash("Product deleted successfully.", "info")
    return redirect('/admin/item-list')

@app.route('/admin/orders')
@admin_login_required
def admin_orders():
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.*, u.name as user_name, u.email as user_email 
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.user_id 
        ORDER BY o.order_id DESC
    """)
    orders = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/admin_orders.html", orders=orders)

@app.route('/admin/update-order-status/<int:order_id>', methods=['POST'])
@admin_login_required
def update_order_status(order_id):
    new_status = request.form.get('status', 'Placed')
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (new_status, order_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Order #{order_id} status updated to '{new_status}'.", "success")
    return redirect('/admin/orders')

# ==========================
# USER AUTHENTICATION
# ==========================
@app.route('/user-register', methods=['GET', 'POST'])
def user_register():
    if request.method == 'GET':
        if 'user_id' in session:
            return redirect('/user-dashboard')
        return render_template("user/user_register.html")
    
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()

    if not name or not email:
        flash("Name and email address are required.", "danger")
        return redirect('/user-register')

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        flash("Email address already registered. Please login.", "warning")
        return redirect('/user-login')
    cur.close()
    conn.close()

    otp = random.randint(100000, 999999)
    session['user_signup_name'] = name
    session['user_signup_email'] = email
    session['user_signup_otp'] = otp

    # Try sending Mail OTP
    try:
        msg = Message("SmartCart Registration OTP Code", sender=config.MAIL_USERNAME, recipients=[email])
        msg.body = f"Hello {name},\n\nYour OTP code for SmartCart registration is: {otp}\n\nEnter this code to create your account password.\n\nThank you,\nSmartCart Team"
        mail.send(msg)
        flash(f"Verification OTP code sent to {email}!", "info")
    except Exception as e:
        print(f"User OTP Mail Error: {e}")
        flash(f"OTP code generated: {otp} (Sent to email / available for test verification)", "info")

    return redirect('/user-verify-otp')

@app.route('/user-verify-otp', methods=['GET', 'POST'])
def user_verify_otp():
    if 'user_signup_email' not in session:
        return redirect('/user-register')
    
    if request.method == 'GET':
        return render_template("user/user_verify_otp.html")
    
    entered_otp = request.form.get('otp', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if str(session.get('user_signup_otp')) != entered_otp:
        flash("Invalid OTP code. Please enter the correct code sent to your email.", "danger")
        return redirect('/user-verify-otp')

    if not password or len(password) < 4:
        flash("Password must be at least 4 characters long.", "danger")
        return redirect('/user-verify-otp')

    if password != confirm_password:
        flash("Passwords do not match.", "danger")
        return redirect('/user-verify-otp')

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
                (session['user_signup_name'], session['user_signup_email'], hashed))
    conn.commit()
    cur.close()
    conn.close()

    session.pop('user_signup_otp', None)
    session.pop('user_signup_name', None)
    session.pop('user_signup_email', None)

    flash("Account registered & password created successfully! Please log in.", "success")
    return redirect('/user-login')

@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'GET':
        if 'user_id' in session:
            return redirect('/user-dashboard')
        return render_template("user/user_login.html")
    
    email = request.form.get('email', '').strip().lower()
    pwd = request.form.get('password', '').strip()

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user or not bcrypt.checkpw(pwd.encode(), user['password'].encode()):
        flash("Invalid email or password.", "danger")
        return redirect('/user-login')

    session['user_id'] = user['user_id']
    session['user_name'] = user['name']
    session['user_email'] = user['email']
    flash(f"Welcome back, {user['name']}!", "success")
    
    next_page = request.args.get('next')
    if next_page:
        return redirect(next_page)
    return redirect('/user-dashboard')

@app.route('/user-dashboard')
def user_dashboard():
    if 'user_id' not in session:
        return redirect('/')
    return redirect('/user/products')

@app.route('/user-logout')
def user_logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_email', None)
    flash("You have been logged out.", "info")
    return redirect('/')

# ==========================
# SHOPPING & CATALOG
# ==========================
@app.route('/user/products')
def user_products():
    search = request.args.get('search', '').strip()
    cat_filter = request.args.get('category', '').strip()
    sort_by = request.args.get('sort', '').strip()

    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM products")
    categories = [c['category'] for c in cur.fetchall() if c.get('category')]

    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        query += " AND (name LIKE %s OR description LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    if cat_filter:
        query += " AND category=%s"
        params.append(cat_filter)
    
    if sort_by == 'price_low':
        query += " ORDER BY price ASC"
    elif sort_by == 'price_high':
        query += " ORDER BY price DESC"
    else:
        query += " ORDER BY product_id DESC"

    cur.execute(query, params)
    products = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('user/user_products.html', products=products, categories=categories, selected_category=cat_filter, search=search, sort_by=sort_by)

@app.route('/user/product/<int:product_id>')
def product_details(product_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE product_id=%s", (product_id,))
    p = cur.fetchone()
    
    if not p:
        cur.close()
        conn.close()
        flash("Product not found.", "warning")
        return redirect('/user/products')

    cur.execute("SELECT * FROM products WHERE category=%s AND product_id!=%s LIMIT 4", (p['category'], product_id))
    related = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('user/product_details.html', product=p, related_products=related)

# ==========================
# CART MANAGEMENT
# ==========================
@app.route('/user/add_to_cart/<int:product_id>')
@user_login_required
def add_to_cart(product_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cart WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    exist = cur.fetchone()

    if exist:
        cur.execute("UPDATE cart SET quantity=quantity+1 WHERE cart_id=%s", (exist['cart_id'],))
    else:
        cur.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, 1)", (session['user_id'], product_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Item added to cart!", "success")
    return redirect('/user/cart')

@app.route('/user/cart')
@user_login_required
def user_cart():
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.cart_id, c.quantity, p.product_id, p.name, p.price, p.original_price, p.image, p.stock_quantity 
        FROM cart c 
        JOIN products p ON c.product_id=p.product_id 
        WHERE c.user_id=%s
    """, (session['user_id'],))
    cart_items = cur.fetchall()
    cur.close()
    conn.close()

    subtotal = sum(float(item['price']) * int(item['quantity']) for item in cart_items) if cart_items else 0
    shipping = 0.0 if subtotal >= 500 or subtotal == 0 else 99.0
    total = subtotal + shipping

    return render_template('user/cart.html', cart_items=cart_items, subtotal=subtotal, shipping=shipping, total=total)

@app.route('/user/cart/increase/<int:product_id>')
@user_login_required
def increase_qty(product_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cart SET quantity=quantity+1 WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect('/user/cart')

@app.route('/user/cart/decrease/<int:product_id>')
@user_login_required
def decrease_qty(product_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT quantity FROM cart WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    row = cur.fetchone()
    
    if row and row['quantity'] > 1:
        cur.execute("UPDATE cart SET quantity=quantity-1 WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    else:
        cur.execute("DELETE FROM cart WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect('/user/cart')

@app.route('/user/cart/remove/<int:product_id>')
@app.route('/user/remove_cart/<int:product_id>')
@user_login_required
def remove_cart(product_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    # Delete by product_id or cart_id
    cur.execute("DELETE FROM cart WHERE user_id=%s AND (product_id=%s OR cart_id=%s)", (session['user_id'], product_id, product_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Item removed from cart.", "info")
    return redirect('/user/cart')

# ==========================
# CHECKOUT & PAYMENT FLOW
# ==========================
@app.route('/user/buy_now/<int:product_id>')
@user_login_required
def buy_now(product_id):
    # Ensure item is in cart or checkout directly
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cart WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    if not cur.fetchone():
        cur.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, 1)", (session['user_id'], product_id))
        conn.commit()
    cur.close()
    conn.close()
    return redirect(f'/user/checkout?buy_now={product_id}')

@app.route('/user/checkout', methods=['GET', 'POST'])
@user_login_required
def user_checkout():
    conn = db.get_db_connection()
    cur = conn.cursor()

    buy_now_id = request.args.get('buy_now')
    if buy_now_id:
        cur.execute("""
            SELECT c.cart_id, c.quantity, p.product_id, p.name, p.price, p.image 
            FROM cart c JOIN products p ON c.product_id=p.product_id 
            WHERE c.user_id=%s AND c.product_id=%s
        """, (session['user_id'], buy_now_id))
    else:
        cur.execute("""
            SELECT c.cart_id, c.quantity, p.product_id, p.name, p.price, p.image 
            FROM cart c JOIN products p ON c.product_id=p.product_id 
            WHERE c.user_id=%s
        """, (session['user_id'],))
    
    cart_items = cur.fetchall()
    
    if not cart_items:
        cur.close()
        conn.close()
        flash("Your cart is empty.", "warning")
        return redirect('/user/products')

    subtotal = sum(float(i['price']) * int(i['quantity']) for i in cart_items)
    shipping = 0.0 if subtotal >= 500 else 99.0
    total = subtotal + shipping

    # Fetch last address if available
    cur.execute("SELECT * FROM addresses WHERE user_id=%s ORDER BY address_id DESC LIMIT 1", (session['user_id'],))
    last_address = cur.fetchone()

    cur.close()
    conn.close()

    selected_ids = [c['cart_id'] for c in cart_items]
    return render_template('user/checkout.html',
                           cart_items=cart_items,
                           subtotal=subtotal,
                           shipping=shipping,
                           total=total,
                           selected_ids=selected_ids,
                           address=last_address)

@app.route('/user/create_razorpay', methods=['POST'])
@user_login_required
def create_razorpay():
    amount = float(request.form.get('total', 0))
    amount_in_paise = int(amount * 100)

    fullname = request.form.get('fullname', session.get('user_name', 'Customer'))
    phone = request.form.get('phone', '')
    address = request.form.get('address', '')
    pincode = request.form.get('pincode', '')

    razorpay_order = None
    if razorpay_client:
        try:
            razorpay_order = razorpay_client.order.create({
                "amount": amount_in_paise,
                "currency": "INR",
                "payment_capture": 1
            })
        except Exception as e:
            print(f"Razorpay Order Creation Error: {e}")

    # Fallback dummy order ID if test keys fail
    if not razorpay_order:
        razorpay_order = {
            "id": f"order_test_{uuid.uuid4().hex[:12]}",
            "amount": amount_in_paise,
            "currency": "INR"
        }

    return render_template('user/razorpay_pay.html',
                           razorpay_order=razorpay_order,
                           total=amount,
                           fullname=fullname,
                           phone=phone,
                           address=address,
                           pincode=pincode,
                           form_data=request.form)

@app.route('/user/verify_payment', methods=['POST'])
@user_login_required
def verify_payment():
    razorpay_order_id = request.form.get('razorpay_order_id', '')
    razorpay_payment_id = request.form.get('razorpay_payment_id', f"pay_test_{uuid.uuid4().hex[:12]}")
    
    return place_order(payment_method="Razorpay UPI / Online",
                       payment_status="Paid",
                       rz_order_id=razorpay_order_id,
                       rz_pay_id=razorpay_payment_id)

@app.route('/user/place_order', methods=['POST'])
@user_login_required
def place_order_route():
    payment_method = request.form.get('payment_method', 'COD')
    if payment_method.startswith('Razorpay'):
        return create_razorpay()
    return place_order(payment_method=payment_method, payment_status="Pending")

def place_order(payment_method="COD", payment_status="Pending", rz_order_id=None, rz_pay_id=None):
    if 'user_id' not in session:
        return redirect('/user-login')

    conn = db.get_db_connection()
    cur = conn.cursor()

    fullname = request.form.get('fullname', session.get('user_name', 'Valued Customer'))
    phone = request.form.get('phone', '')
    address = request.form.get('address', '')
    city = request.form.get('city', '')
    pincode = request.form.get('pincode', '')

    full_address = f"{fullname}, {address}, {city} - {pincode}, Phone: {phone}"

    # Get user cart items
    cur.execute("""
        SELECT c.cart_id, c.product_id, c.quantity, p.price 
        FROM cart c 
        JOIN products p ON c.product_id=p.product_id 
        WHERE c.user_id=%s
    """, (session['user_id'],))
    cart_items = cur.fetchall()

    if not cart_items:
        cur.close()
        conn.close()
        flash("Your cart is empty!", "warning")
        return redirect('/user/cart')

    subtotal = sum(float(i['price']) * int(i['quantity']) for i in cart_items)
    shipping = 0.0 if subtotal >= 500 else 99.0
    total_amount = subtotal + shipping

    order_number = f"ORD-{random.randint(100000, 999999)}"

    # Save Address
    if fullname and address:
        cur.execute("""
            INSERT INTO addresses (user_id, full_name, phone, address, city, pincode) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (session['user_id'], fullname, phone, address, city, pincode))

    # Create Order
    cur.execute("""
        INSERT INTO orders (user_id, order_number, total_amount, address, payment_method, payment_status, razorpay_order_id, razorpay_payment_id, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Placed')
    """, (session['user_id'], order_number, total_amount, full_address, payment_method, payment_status, rz_order_id, rz_pay_id))
    
    order_id = cur.lastrowid

    # Create Order Items & Decrement Stock
    for item in cart_items:
        cur.execute("""
            INSERT INTO order_items (order_id, product_id, quantity, price) 
            VALUES (%s, %s, %s, %s)
        """, (order_id, item['product_id'], item['quantity'], float(item['price'])))
        
        cur.execute("UPDATE products SET stock_quantity = stock_quantity - %s WHERE product_id=%s AND stock_quantity >= %s", 
                    (item['quantity'], item['product_id'], item['quantity']))

    # Clear User Cart
    cur.execute("DELETE FROM cart WHERE user_id=%s", (session['user_id'],))
    conn.commit()
    cur.close()
    conn.close()

    flash("Order placed successfully!", "success")
    return redirect(f'/user/order_success/{order_id}')

@app.route('/user/order_success/<int:order_id>')
@user_login_required
def order_success(order_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id=%s AND user_id=%s", (order_id, session['user_id']))
    order = cur.fetchone()

    if not order:
        cur.close()
        conn.close()
        return redirect('/user/orders')

    cur.execute("""
        SELECT oi.*, p.name, p.image 
        FROM order_items oi 
        JOIN products p ON oi.product_id=p.product_id 
        WHERE oi.order_id=%s
    """, (order_id,))
    order_items = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('user/order_success.html', order=order, order_items=order_items)

# ==========================
# USER ORDERS
# ==========================
@app.route('/user/orders')
@app.route('/user/my-orders')
@app.route('/user/my_orders')
@user_login_required
def user_orders():
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY order_id DESC", (session['user_id'],))
    orders = cur.fetchall()

    orders_with_items = []
    for order in orders:
        cur.execute("""
            SELECT oi.*, p.name, p.image 
            FROM order_items oi 
            JOIN products p ON oi.product_id=p.product_id 
            WHERE oi.order_id=%s
        """, (order['order_id'],))
        items = cur.fetchall()
        order_dict = dict(order)
        if order_dict.get('created_at'):
            order_dict['created_at'] = str(order_dict['created_at'])
        else:
            order_dict['created_at'] = 'Recent'
        order_dict['total_amount'] = float(order_dict.get('total_amount') or 0.0)
        order_dict['order_items'] = items
        orders_with_items.append(order_dict)

    cur.close()
    conn.close()
    return render_template('user/my_orders.html', orders=orders_with_items)

@app.route('/user/cancel_order/<int:order_id>', methods=['POST', 'GET'])
@user_login_required
def cancel_order(order_id):
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM orders WHERE order_id=%s AND user_id=%s", (order_id, session['user_id']))
    order = cur.fetchone()

    if order and order['status'] in ('Placed', 'Processing'):
        cur.execute("UPDATE orders SET status='Cancelled' WHERE order_id=%s", (order_id,))
        conn.commit()
        flash(f"Order #{order_id} cancelled successfully.", "info")
    else:
        flash("Order cannot be cancelled at this stage.", "danger")

    cur.close()
    conn.close()
    return redirect('/user/orders')

# ==========================
# ERROR HANDLERS
# ==========================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="404 Page Not Found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('index.html', error="Internal Server Error"), 500

if __name__ == '__main__':
    print("Starting SMART CART Application on http://127.0.0.1:5000 ...")
    app.run(debug=True, port=5000)