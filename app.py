from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from passlib.hash import bcrypt
import mysql.connector
from functools import wraps
import os
from dotenv import load_dotenv

load_dotenv()


app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')  # Replace with a secure random key in production

# Database Configuration

db_config = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except mysql.connector.Error as e:
        flash(f"Database connection error: {e}", 'danger')
        return None

# Login Required Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("You need to log in first.", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    user_id = session.get('user_id')  # Ensure user ID is fetched for filtering trips

    if request.method == 'GET':
        # Retrieve trips data for the logged-in user
        conn = get_db_connection()
        if conn is None:
            print("1")
            return render_template("index.html", trips=[])

        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT *
                FROM trips 
                WHERE user_id = %s
            """
            cursor.execute(query, (user_id,))
            trips = cursor.fetchall()
            return render_template("index.html", trips=trips)
        except mysql.connector.Error as e:
            print("2")
            return render_template("index.html", trips=[])
        finally:
            cursor.close()
            conn.close()

    if request.method == 'POST':
        # Retrieve data from the form
        trip_name = request.form.get('tripName')
        destination = request.form.get('tripDestination')

        if not trip_name or not destination:
            return jsonify({"error": "'tripName' and 'destination' are required."}), 400

        conn = get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection failed."}), 500

        try:
            cursor = conn.cursor()
            query = """
                INSERT INTO trips (user_id, trip_name, destination) 
                VALUES (%s, %s, %s)
            """
            cursor.execute(query, (user_id, trip_name, destination))
            conn.commit()
            return redirect(url_for('index'))
        except mysql.connector.Error as e:
            return jsonify({"error": f"Database error: {e}"}), 500
        finally:
            cursor.close()
            conn.close()


@app.route('/trip/<int:trip_id>', methods=['GET'])
@login_required
def trip_details(trip_id):
    user_id = session.get('user_id')  # Ensure user is authenticated
    conn = get_db_connection()
    if conn is None:
        return render_template("expense.html", expenses=[], trip_id=trip_id, trip_name="Unknown")

    try:
        cursor = conn.cursor(dictionary=True)

        # Fetch trip_name based on trip_id
        trip_name_query = """
            SELECT trip_name 
            FROM trips
            WHERE trip_id = %s AND user_id = %s
        """
        cursor.execute(trip_name_query, (trip_id, user_id))
        trip_row = cursor.fetchone()
        trip_name = trip_row['trip_name'] if trip_row else "Unknown"

        # Fetch expenses for the selected trip
        expenses_query = """
            SELECT *
            FROM expenses
            WHERE trip_id = %s AND user_id = %s
        """
        cursor.execute(expenses_query, (trip_id, user_id))
        expenses = cursor.fetchall()

        return render_template("expense.html", expenses=expenses, trip_id=trip_id, trip_name=trip_name)
    except mysql.connector.Error as e:
        return render_template("expense.html", expenses=[], trip_id=trip_id, trip_name="Error")
    finally:
        cursor.close()
        conn.close()

@app.route('/expense/<int:trip_id>', methods=['GET'])
@login_required
def expense(trip_id):
    user_id = session.get('user_id')  # Ensure user is authenticated
    conn = get_db_connection()
    
    if conn is None:
        return render_template("expense_chart.html", cost=[], trip_id=trip_id, trip_name="Unknown")

    try:
        cursor = conn.cursor(dictionary=True)

        # Fetch trip_name based on trip_id
        trip_name_query = """
            SELECT trip_name 
            FROM trips
            WHERE trip_id = %s AND user_id = %s
        """
        cursor.execute(trip_name_query, (trip_id, user_id))
        trip_row = cursor.fetchone()
        trip_name = trip_row['trip_name'] if trip_row else "Unknown"

        # Fetch the total sum of 'General' category expenses for the selected trip
        expenses_query = """
            SELECT 
                SUM(CASE WHEN category = 'General' THEN amount ELSE 0 END) AS general_amount,
                SUM(CASE WHEN category = 'Food' THEN amount ELSE 0 END) AS food_amount,
                SUM(CASE WHEN category = 'Travel' THEN amount ELSE 0 END) AS travel_amount,
                SUM(CASE WHEN category = 'Night Stay' THEN amount ELSE 0 END) AS night_stay_amount,
                SUM(amount) AS total_amount
            FROM expenses
            WHERE trip_id = %s
            AND user_id = %s

        """
        cursor.execute(expenses_query, (trip_id, user_id))
        cost = cursor.fetchone()  # Since it's a SUM query, use fetchone() to get a single row

        return render_template("expense_chart.html", cost=cost, trip_id=trip_id, trip_name=trip_name)

    except mysql.connector.Error as e:
        # Handle errors and render with an error message
        return render_template("expense_chart.html", cost=[], trip_id=trip_id, trip_name="Error")
    finally:
        cursor.close()
        conn.close()

@app.route('/addexpense/<int:trip_id>', methods=['GET', 'POST'])
@login_required
def addexpense(trip_id):
    if request.method == 'GET':
        return render_template("expense_create.html")

    if request.method == 'POST':
        user_id = session.get('user_id')  # Ensure the user is authenticated
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 403

        # Get form data
        category = request.form.get('category')
        amount = request.form.get('amount')
        description = request.form.get('description', '') or "none"
        location = request.form.get('location', '') or "none"
        method = request.form.get('method')

        # Validate required fields
        if not category or not amount or not method:
            flash("Category, amount, and payment method are required.", "error")
            return redirect(request.url)
        if amount is None or float(amount) <= 0:
            flash("Amount must be greater than zero.", "error")
            return redirect(request.url)

        # Validate numeric fields
        try:
            amount = float(amount)
            if amount <= 0:
                return jsonify({"error": "Amount must be a positive number"}), 400
        except ValueError:
            return jsonify({"error": "Invalid amount format"}), 400

        # Database connection
        conn = get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection failed"}), 500

        try:
            cursor = conn.cursor()
            query = """
                INSERT INTO expenses (user_id, trip_id, category, amount, description, location, method) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (user_id, trip_id, category, amount, description, location, method))
            conn.commit()
            return redirect(url_for('expense', trip_id=trip_id))
        except mysql.connector.Error as e:
            conn.rollback()  # Rollback in case of error
            return jsonify({"error": f"Database error: {e}"}), 500
        finally:
            cursor.close()
            conn.close()

@app.route('/deleteexpense/<int:expense_id>', methods=['POST'])
@login_required
def deleteexpense(expense_id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor()
        query = """
            DELETE FROM expenses
            WHERE expense_id = %s AND user_id = %s
        """
        cursor.execute(query, (expense_id, user_id))
        conn.commit()
        return jsonify({"message": "Expense deleted successfully."}), 200
    except mysql.connector.Error as e:
        conn.rollback()
        return jsonify({"error": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()   

# Route: Signup
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = bcrypt.hash(password)
        
        conn = get_db_connection()
        if conn is None:
            flash("Database connection failed.", 'danger')
            return redirect(url_for('signup'))
        
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                flash('Username already exists. Please choose another.', 'warning')
                return redirect(url_for('signup'))
            
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)", 
                (username, hashed_password)
            )
            conn.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except mysql.connector.Error as e:
            flash(f"Error creating account: {e}", 'danger')
        finally:
            cursor.close()
            conn.close()
    return render_template('signup.html')

# Route: Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        if conn is None:
            flash("Database connection failed.", 'danger')
            return redirect(url_for('login'))
        
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user:
                flash('Username does not exist. Please sign up.', 'warning')
                return redirect(url_for('signup'))
            
            if bcrypt.verify(password, user['password']):
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                flash('Logged in successfully!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Incorrect password. Please try again.', 'danger')
        except mysql.connector.Error as e:
            flash(f"Error during login: {e}", 'danger')
        finally:
            cursor.close()
            conn.close()
    return render_template('login.html')

# Route: Logout
@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("Logged out successfully.", 'success')
    return redirect(url_for('login'))


@app.errorhandler(415)
def unsupported_media_type(e):
    return jsonify({"error": "Unsupported Media Type. Please use 'application/json' for your request."}), 415


if __name__ == '__main__':
    app.run(debug=True)
