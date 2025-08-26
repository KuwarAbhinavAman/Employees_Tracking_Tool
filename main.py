import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from dateutil.relativedelta import relativedelta
import calendar
import warnings
import requests
import smtplib
from email.mime.text import MIMEText

warnings.filterwarnings('ignore')

# Database connection function
def get_db_connection():
    conn = sqlite3.connect('employee_tracking.db', check_same_thread=False)
    return conn

# Initialize database and tables
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create tables if they don't exist
    c.execute('''CREATE TABLE IF NOT EXISTS employees (
        emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        role TEXT,
        department TEXT,
        salary REAL,
        expected_login TEXT,
        expected_logout TEXT,
        hire_date TEXT,
        status TEXT DEFAULT 'Active'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        att_id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER,
        login_time TEXT,
        break_duration INTEGER,
        logout_time TEXT,
        notes TEXT,
        FOREIGN KEY(emp_id) REFERENCES employees(emp_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER,
        task_name TEXT,
        description TEXT,
        assigned_date TEXT,
        due_date TEXT,
        submission_date TEXT,
        status TEXT,
        priority TEXT,
        FOREIGN KEY(emp_id) REFERENCES employees(emp_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        exp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        amount REAL,
        month TEXT,
        description TEXT,
        emp_id INTEGER,
        FOREIGN KEY(emp_id) REFERENCES employees(emp_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS revenues (
        rev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        amount REAL,
        month TEXT,
        description TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS performance_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER,
        review_date TEXT,
        rating INTEGER,
        comments TEXT,
        reviewer TEXT,
        FOREIGN KEY(emp_id) REFERENCES employees(emp_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS leaves (
        leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        type TEXT,
        status TEXT DEFAULT 'Pending',
        reason TEXT,
        FOREIGN KEY(emp_id) REFERENCES employees(emp_id)
    )''')
    
    # Check and add missing columns in employees table
    c.execute("PRAGMA table_info(employees)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'department' not in columns:
        c.execute("ALTER TABLE employees ADD COLUMN department TEXT")
        c.execute("UPDATE employees SET department = 'Unknown' WHERE department IS NULL")
    
    if 'status' not in columns:
        c.execute("ALTER TABLE employees ADD COLUMN status TEXT DEFAULT 'Active'")
        c.execute("UPDATE employees SET status = 'Active' WHERE status IS NULL")
    
    if 'hire_date' not in columns:
        c.execute("ALTER TABLE employees ADD COLUMN hire_date TEXT")
        c.execute("UPDATE employees SET hire_date = '2023-01-01' WHERE hire_date IS NULL")
    
    # Check and add emp_id column to expenses table if missing
    c.execute("PRAGMA table_info(expenses)")
    exp_columns = [col[1] for col in c.fetchall()]
    if 'emp_id' not in exp_columns:
        c.execute("ALTER TABLE expenses ADD COLUMN emp_id INTEGER")
    
    conn.commit()
    conn.close()

# Function to fetch data as DataFrame
def fetch_data(query, params=None):
    conn = get_db_connection()
    try:
        if params:
            df = pd.read_sql_query(query, conn, params=params)
        else:
            df = pd.read_sql_query(query, conn)
        return df
    except Exception as err:
        st.error(f"Error fetching data: {err}")
        return pd.DataFrame()
    finally:
        conn.close()

# Function to execute insert/update/delete queries or fetch results for SELECT queries
def execute_query(query, params=None, return_last_id=False):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if params:
            c.execute(query, params)
        else:
            c.execute(query)
        
        if query.strip().upper().startswith("SELECT"):
            result = c.fetchall()
            conn.close()  # Close here since no commit needed for SELECT
            return result
        else:
            conn.commit()
            if return_last_id:
                last_id = c.lastrowid
                conn.close()
                return last_id
            conn.close()
            st.success("Operation successful!")
            return None
    except Exception as err:
        st.error(f"Error executing query: {err}")
        conn.close()
        return None

# Calculate working hours
def calculate_working_hours(login, logout, break_duration):
    if not login or not logout:
        return 0
    try:
        login_dt = datetime.strptime(login, '%Y-%m-%d %H:%M:%S')
        logout_dt = datetime.strptime(logout, '%Y-%m-%d %H:%M:%S')
        delta = logout_dt - login_dt
        hours = delta.total_seconds() / 3600 - (break_duration / 60)
        return max(hours, 0)
    except ValueError:
        return 0

# Calculate late/early minutes
def calculate_late_early(actual_login, expected_login, actual_logout, expected_logout):
    if not actual_login or not expected_login or not actual_logout or not expected_logout:
        return 0, 0
    try:
        actual_login_dt = datetime.strptime(actual_login, '%Y-%m-%d %H:%M:%S')
        expected_login_dt = datetime.strptime(expected_login, '%H:%M:%S').replace(year=actual_login_dt.year, month=actual_login_dt.month, day=actual_login_dt.day)
        actual_logout_dt = datetime.strptime(actual_logout, '%Y-%m-%d %H:%M:%S')
        expected_logout_dt = datetime.strptime(expected_logout, '%H:%M:%S').replace(year=actual_logout_dt.year, month=actual_logout_dt.month, day=actual_logout_dt.day)
        late = (actual_login_dt - expected_login_dt).total_seconds() / 60 if actual_login_dt > expected_login_dt else 0
        early = (expected_logout_dt - actual_logout_dt).total_seconds() / 60 if actual_logout_dt < expected_logout_dt else 0
        return late, early
    except ValueError:
        return 0, 0

# Function to combine date and time inputs
def combine_date_time(date_input, time_input):
    if date_input and time_input:
        return datetime.combine(date_input, time_input).strftime('%Y-%m-%d %H:%M:%S')
    return None

# Add salary to expenses
def add_salary_to_expenses(emp_id, amount, month, name):
    execute_query(
        "INSERT INTO expenses (category, amount, month, description, emp_id) VALUES (?, ?, ?, ?, ?)",
        ("Salary", amount, month, f"Salary for {name} (ID: {emp_id})", emp_id)
    )

# Calculate employee tenure
def calculate_tenure(hire_date):
    if not hire_date or (isinstance(hire_date, pd.Timestamp) and pd.isna(hire_date)):
        return "N/A"
    try:
        if isinstance(hire_date, pd.Timestamp):
            hire_dt = hire_date.to_pydatetime()
        else:
            hire_dt = datetime.strptime(hire_date, '%Y-%m-%d')
        today = datetime.now()
        delta = relativedelta(today, hire_dt)
        return f"{delta.years} years, {delta.months} months"
    except ValueError:
        return "N/A"

# Function to get AI insights using Groq API
def get_grok_insights(user_data, prediction):
    GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    
    if not GROQ_API_KEY:
        return {
            "recommendations": [
                "1. General: Review pricing strategy (Reason: API key not configured)",
                "2. Marketing: Optimize channels (Reason: Default recommendation)"
            ],
            "error": "API key not configured"
        }

    try:
        prompt = f"""
        As an expert subscription consultant, provide 3-5 specific recommendations and action plan for optimizing subscription likelihood 
        based on this user data:
        - Price: {user_data.get('price', 0)}
        - Age: {user_data.get('age', 0)}
        - Income: {user_data.get('income', 0)}
        - Trial Used: {'Yes' if user_data.get('trial_used', 0) else 'No'}
        - Marketing Channel: {user_data.get('marketing_channel', 'Unknown')}
        - Predicted Subscription Probability: {prediction * 100:.1f}%
        Format:
        [Priority]. [Area]: [Action] (Rationale: [brief explanation])
        """

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "llama3-70b-8192",
            "messages": [
                {"role": "system", "content": "You are an expert subscription consultant providing concise, actionable recommendations."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }

        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return {
            "recommendations": result['choices'][0]['message']['content'].split('\n'),
            "error": None
        }
    except Exception as e:
        return {
            "recommendations": [
                "1. System: Technical issue occurred (Reason: Unexpected error)",
                "2. General: Optimize marketing (Reason: Default recommendation)"
            ],
            "error": f"Unexpected Error: {str(e)}"
        }

# Function to notify admin via email about new leave request
def notify_admin_leave_request(name, start_date, end_date, leave_type, reason):
    sender = "abhinavabby9@gmail.com"
    receiver = sender
    password = "Imthebestg@121"
    subject = "New Leave Request"
    body = f"New leave request from {name}: {leave_type} from {start_date} to {end_date}. Reason: {reason}"

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
        server.quit()
    except Exception as e:
        pass

# Function to automatically add salaries to expenses for the current month
def auto_add_salaries():
    current_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    employees = fetch_data("SELECT emp_id, name, salary FROM employees WHERE status = 'Active'")
    existing_expenses = fetch_data("SELECT emp_id FROM expenses WHERE category = 'Salary' AND month = ?", (current_month,))
    existing_emp_ids = set(existing_expenses['emp_id'].values) if not existing_expenses.empty else set()
    
    for index, row in employees.iterrows():
        if row['emp_id'] not in existing_emp_ids:
            add_salary_to_expenses(row['emp_id'], row['salary'], current_month, row['name'])

# Initialize database and add salaries on app start
init_db()
auto_add_salaries()

# Streamlit App
st.set_page_config(page_title="Employee Tracking Tool", layout="wide")
st.title("Employee Tracking Tool")

# Initialize session state for admin login
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

# Month and year selector options
months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
current_year = datetime.now().year
years = list(range(current_year - 5, current_year + 1))

# Sidebar for navigation
page = st.sidebar.selectbox("Select Page", [
    "Dashboard",
    "Admin Panel",
    "Attendance Tracking",
    "Productivity Tracking",
    "Payroll Calculation",
    "Expense & Revenue Analysis",
    "Performance Reviews",
    "Leave Management"
])

# Automatic logout when switching from Admin Panel to another page
if 'last_page' not in st.session_state:
    st.session_state.last_page = page

if page != st.session_state.last_page and st.session_state.get('admin_logged_in', False):
    if st.session_state.last_page == "Admin Panel" and page != "Admin Panel":
        st.session_state.admin_logged_in = False
        st.warning("Logged out of Admin Panel for privacy and security reasons.")
        # No rerun here to avoid loop; the warning will show on the new page

st.session_state.last_page = page

# Dashboard
if page == "Dashboard":
    st.header("Company Dashboard")
    
    col1, col2, col3, col4 = st.columns(4)
    
    employees = fetch_data("SELECT COUNT(*) as count FROM employees WHERE status = 'Active'")
    emp_count = employees['count'].iloc[0] if not employees.empty else 0
    col1.metric("Total Employees", emp_count)
    
    today = datetime.now().strftime('%Y-%m-%d')
    attendance = fetch_data("SELECT COUNT(*) as count FROM attendance WHERE date(login_time) = ?", (today,))
    att_count = attendance['count'].iloc[0] if not attendance.empty else 0
    col2.metric("Today's Attendance", att_count)
    
    tasks = fetch_data("SELECT COUNT(*) as count FROM tasks WHERE status = 'Pending'")
    task_count = tasks['count'].iloc[0] if not tasks.empty else 0
    col3.metric("Pending Tasks", task_count)
    
    current_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    expenses = fetch_data("SELECT SUM(amount) as total FROM expenses WHERE month = ?", (current_month,))
    exp_total = expenses['total'].iloc[0] if not expenses.empty and not pd.isna(expenses['total'].iloc[0]) else 0
    col4.metric("Monthly Expenses", f"₹{exp_total:,.2f}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        dept_data = fetch_data("SELECT department, COUNT(*) as count FROM employees WHERE status = 'Active' GROUP BY department")
        if not dept_data.empty:
            fig = px.pie(dept_data, values='count', names='department', title='Employee Distribution by Department')
            st.plotly_chart(fig)
    
    with col2:
        exp_trend = fetch_data("SELECT month, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month")
        if not exp_trend.empty:
            exp_trend['month'] = pd.to_datetime(exp_trend['month'])
            fig = px.line(exp_trend, x='month', y='total', title='Monthly Expense Trend')
            st.plotly_chart(fig)
    
    st.subheader("Recent Activities")
    
    recent_att = fetch_data("""
        SELECT a.login_time, e.name 
        FROM attendance a 
        JOIN employees e ON a.emp_id = e.emp_id 
        ORDER BY a.login_time DESC 
        LIMIT 5
    """)
    if not recent_att.empty:
        st.write("**Recent Check-ins:**")
        for _, row in recent_att.iterrows():
            st.write(f"{row['name']} - {row['login_time']}")
    
    recent_tasks = fetch_data("""
        SELECT t.task_name, e.name, t.status 
        FROM tasks t 
        JOIN employees e ON t.emp_id = e.emp_id 
        ORDER BY t.assigned_date DESC 
        LIMIT 5
    """)
    if not recent_tasks.empty:
        st.write("**Recent Tasks:**")
        for _, row in recent_tasks.iterrows():
            st.write(f"{row['name']} - {row['task_name']} ({row['status']})")

# Admin Panel
if page == "Admin Panel":
    st.header("Admin Panel - Data Entry")
    if not st.session_state.admin_logged_in:
        st.subheader("Admin Login")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if email == "abhinavabby9@gmail.com" and password == "Imthebestg@121":
                st.session_state.admin_logged_in = True
                st.success("Logged in successfully!")
                st.rerun()
            else:
                st.error("Invalid credentials")
    else:
        if st.button("Logout"):
            st.session_state.admin_logged_in = False
            st.rerun()

        pending = fetch_data("SELECT COUNT(*) as count FROM leaves WHERE status = 'Pending'")['count'].iloc[0]
        if pending > 0:
            st.warning(f"There are {pending} pending leave requests!")

        tabs = st.tabs(["Employees", "Attendance", "Tasks", "Expenses", "Revenues", "Leave Approvals"])

        with tabs[0]:
            st.subheader("Add Employee")
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Name", key="emp_name")
                role = st.text_input("Role", key="emp_role")
                department = st.selectbox("Department", ["HR", "Engineering", "Sales", "Marketing", "Operations", "Finance"], key="emp_department")
                salary = st.number_input("Monthly Salary (₹)", min_value=0.0, step=1000.0, key="emp_salary")
            with col2:
                expected_login = st.time_input("Expected Login Time", key="emp_login_time")
                expected_logout = st.time_input("Expected Logout Time", key="emp_logout_time")
                hire_date = st.date_input("Hire Date", key="emp_hire_date")
                status = st.selectbox("Status", ["Active", "Inactive"], key="emp_status")
            
            if st.button("Add Employee", key="add_employee"):
                if name and role and department and salary and hire_date:
                    last_id = execute_query(
                        "INSERT INTO employees (name, role, department, salary, expected_login, expected_logout, hire_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (name, role, department, salary, expected_login.strftime('%H:%M:%S'), expected_logout.strftime('%H:%M:%S'), hire_date.strftime('%Y-%m-%d'), status),
                        return_last_id=True
                    )
                    current_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
                    add_salary_to_expenses(last_id, salary, current_month, name)
                else:
                    st.error("Please fill all required fields.")

            st.subheader("View/Update/Delete Employees")
            employees = fetch_data("SELECT * FROM employees")
            if not employees.empty:
                employees['hire_date'] = pd.to_datetime(employees['hire_date'], errors='coerce')
                employees['tenure'] = employees['hire_date'].apply(calculate_tenure)
                edited_df = st.data_editor(employees, num_rows="dynamic", use_container_width=True, hide_index=False, column_config={
                    "emp_id": st.column_config.NumberColumn("ID", disabled=True),
                    "name": st.column_config.TextColumn("Name"),
                    "role": st.column_config.TextColumn("Role"),
                    "department": st.column_config.SelectboxColumn("Department", options=["HR", "Engineering", "Sales", "Marketing", "Operations", "Finance"]),
                    "salary": st.column_config.NumberColumn("Salary"),
                    "expected_login": st.column_config.TextColumn("Expected Login"),
                    "expected_logout": st.column_config.TextColumn("Expected Logout"),
                    "hire_date": st.column_config.DateColumn("Hire Date"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Active", "Inactive"]),
                    "tenure": st.column_config.TextColumn("Tenure", disabled=True),
                }, key="emp_data_editor")
                if st.button("Update Employees", key="update_employees"):
                    for index, row in edited_df.iterrows():
                        hire_date_str = row['hire_date'].strftime('%Y-%m-%d') if pd.notna(row['hire_date']) else '2023-01-01'
                        execute_query(
                            "UPDATE employees SET name = ?, role = ?, department = ?, salary = ?, expected_login = ?, expected_logout = ?, hire_date = ?, status = ? WHERE emp_id = ?",
                            (row['name'], row['role'], row['department'], row['salary'], row['expected_login'], row['expected_logout'], hire_date_str, row['status'], row['emp_id'])
                        )
                        # Update or add salary to expenses if employee is active
                        if row['status'] == 'Active':
                            current_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
                            existing_expense = fetch_data("SELECT exp_id, amount FROM expenses WHERE category = 'Salary' AND month = ? AND emp_id = ?", (current_month, row['emp_id']))
                            if not existing_expense.empty:
                                execute_query(
                                    "UPDATE expenses SET amount = ?, description = ? WHERE exp_id = ?",
                                    (row['salary'], f"Salary for {row['name']} (ID: {row['emp_id']})", existing_expense['exp_id'].iloc[0])
                                )
                            else:
                                add_salary_to_expenses(row['emp_id'], row['salary'], current_month, row['name'])
                st.subheader("Delete Employees")
                delete_emp_ids = st.multiselect("Select Employees to Delete", options=employees['emp_id'], format_func=lambda x: employees[employees['emp_id'] == x]['name'].values[0], key="delete_emp_select")
                if st.button("Delete Selected Employees", key="delete_employees"):
                    for emp_id in delete_emp_ids:
                        execute_query("DELETE FROM employees WHERE emp_id = ?", (emp_id,))
                        execute_query("DELETE FROM attendance WHERE emp_id = ?", (emp_id,))
                        execute_query("DELETE FROM tasks WHERE emp_id = ?", (emp_id,))
                        execute_query("DELETE FROM performance_reviews WHERE emp_id = ?", (emp_id,))
                        execute_query("DELETE FROM leaves WHERE emp_id = ?", (emp_id,))
                        execute_query("DELETE FROM expenses WHERE emp_id = ?", (emp_id,))
            else:
                st.info("No employees found.")

        with tabs[1]:
            st.subheader("Add Attendance")
            employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
            if not employees.empty:
                emp_id = st.selectbox("Select Employee", options=employees['emp_id'], format_func=lambda x: employees[employees['emp_id'] == x]['name'].values[0], key="attendance_emp_select")
                col1, col2 = st.columns(2)
                with col1:
                    login_date = st.date_input("Login Date", key="att_login_date")
                    login_time = st.time_input("Login Time", key="att_login_time")
                with col2:
                    logout_date = st.date_input("Logout Date", key="att_logout_date")
                    logout_time = st.time_input("Logout Time", key="att_logout_time")
                break_duration = st.number_input("Break Duration (minutes)", min_value=0, step=5, key="att_break_duration")
                notes = st.text_area("Notes", key="att_notes")
                login_datetime = combine_date_time(login_date, login_time)
                logout_datetime = combine_date_time(logout_date, logout_time)
                if st.button("Add Attendance", key="add_attendance"):
                    if emp_id and login_datetime and logout_datetime:
                        if datetime.strptime(logout_datetime, '%Y-%m-%d %H:%M:%S') > datetime.strptime(login_datetime, '%Y-%m-%d %H:%M:%S'):
                            execute_query(
                                "INSERT INTO attendance (emp_id, login_time, break_duration, logout_time, notes) VALUES (?, ?, ?, ?, ?)",
                                (emp_id, login_datetime, break_duration, logout_datetime, notes)
                            )
                        else:
                            st.error("Logout time must be after login time.")
                    else:
                        st.error("Please fill all required fields.")
            else:
                st.info("No active employees found. Add employees first.")

            st.subheader("View/Update/Delete Attendance")
            attendance = fetch_data("SELECT a.*, e.name FROM attendance a JOIN employees e ON a.emp_id = e.emp_id")
            if not attendance.empty:
                attendance['login_time'] = pd.to_datetime(attendance['login_time'])
                attendance['logout_time'] = pd.to_datetime(attendance['logout_time'])
                edited_df = st.data_editor(attendance, num_rows="dynamic", use_container_width=True, hide_index=False, column_config={
                    "att_id": st.column_config.NumberColumn("ID", disabled=True),
                    "emp_id": st.column_config.NumberColumn("Employee ID", disabled=True),
                    "name": st.column_config.TextColumn("Name", disabled=True),
                    "login_time": st.column_config.DatetimeColumn("Login Time"),
                    "logout_time": st.column_config.DatetimeColumn("Logout Time"),
                    "break_duration": st.column_config.NumberColumn("Break Duration"),
                    "notes": st.column_config.TextColumn("Notes"),
                }, key="att_data_editor")
                if st.button("Update Attendance", key="update_attendance"):
                    for index, row in edited_df.iterrows():
                        execute_query(
                            "UPDATE attendance SET login_time = ?, break_duration = ?, logout_time = ?, notes = ? WHERE att_id = ?",
                            (row['login_time'].strftime('%Y-%m-%d %H:%M:%S'), row['break_duration'], row['logout_time'].strftime('%Y-%m-%d %H:%M:%S'), row['notes'], row['att_id'])
                        )
                st.subheader("Delete Attendance")
                delete_att_ids = st.multiselect("Select Attendance Records to Delete", options=attendance['att_id'], key="delete_att_select")
                if st.button("Delete Selected Attendance", key="delete_attendance"):
                    for att_id in delete_att_ids:
                        execute_query("DELETE FROM attendance WHERE att_id = ?", (att_id,))
            else:
                st.info("No attendance data available.")

        with tabs[2]:
            st.subheader("Add Task")
            employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
            if not employees.empty:
                emp_id = st.selectbox("Select Employee", options=employees['emp_id'], format_func=lambda x: employees[employees['emp_id'] == x]['name'].values[0], key="task_emp_select")
                task_name = st.text_input("Task Name", key="task_name")
                description = st.text_area("Description", key="task_description")
                col1, col2 = st.columns(2)
                with col1:
                    assigned_date = st.date_input("Assigned Date", key="task_assigned_date")
                    due_date = st.date_input("Due Date", key="task_due_date")
                with col2:
                    submission_date = st.date_input("Submission Date", value=None, key="task_submission_date")
                    priority = st.selectbox("Priority", ["Low", "Medium", "High"], key="task_priority")
                status = st.selectbox("Status", ["Pending", "In Progress", "Completed On-Time", "Completed Late", "Cancelled"], key="task_status")
                if st.button("Add Task", key="add_task"):
                    if emp_id and task_name and assigned_date and due_date:
                        execute_query(
                            "INSERT INTO tasks (emp_id, task_name, description, assigned_date, due_date, submission_date, status, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (emp_id, task_name, description, assigned_date.strftime('%Y-%m-%d'), due_date.strftime('%Y-%m-%d'), submission_date.strftime('%Y-%m-%d') if submission_date else None, status, priority)
                        )
                    else:
                        st.error("Please fill all required fields.")
            else:
                st.info("No active employees found. Add employees first.")

            st.subheader("View/Update/Delete Tasks")
            tasks = fetch_data("SELECT t.*, e.name FROM tasks t JOIN employees e ON t.emp_id = e.emp_id")
            if not tasks.empty:
                tasks['assigned_date'] = pd.to_datetime(tasks['assigned_date'])
                tasks['due_date'] = pd.to_datetime(tasks['due_date'])
                tasks['submission_date'] = pd.to_datetime(tasks['submission_date'], errors='coerce')
                edited_df = st.data_editor(tasks, num_rows="dynamic", use_container_width=True, hide_index=False, column_config={
                    "task_id": st.column_config.NumberColumn("ID", disabled=True),
                    "emp_id": st.column_config.NumberColumn("Employee ID", disabled=True),
                    "name": st.column_config.TextColumn("Name", disabled=True),
                    "task_name": st.column_config.TextColumn("Task Name"),
                    "description": st.column_config.TextColumn("Description"),
                    "assigned_date": st.column_config.DateColumn("Assigned Date"),
                    "due_date": st.column_config.DateColumn("Due Date"),
                    "submission_date": st.column_config.DateColumn("Submission Date"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Pending", "In Progress", "Completed On-Time", "Completed Late", "Cancelled"]),
                    "priority": st.column_config.SelectboxColumn("Priority", options=["Low", "Medium", "High"]),
                }, key="task_data_editor")
                if st.button("Update Tasks", key="update_tasks"):
                    for index, row in edited_df.iterrows():
                        execute_query(
                            "UPDATE tasks SET task_name = ?, description = ?, assigned_date = ?, due_date = ?, submission_date = ?, status = ?, priority = ? WHERE task_id = ?",
                            (row['task_name'], row['description'], row['assigned_date'].strftime('%Y-%m-%d'), row['due_date'].strftime('%Y-%m-%d'), row['submission_date'].strftime('%Y-%m-%d') if pd.notna(row['submission_date']) else None, row['status'], row['priority'], row['task_id'])
                        )
                st.subheader("Delete Tasks")
                delete_task_ids = st.multiselect("Select Tasks to Delete", options=tasks['task_id'], key="delete_task_select")
                if st.button("Delete Selected Tasks", key="delete_tasks"):
                    for task_id in delete_task_ids:
                        execute_query("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            else:
                st.info("No tasks data available.")

        with tabs[3]:
            st.subheader("Add Expense")
            category = st.selectbox("Category", ["Rent", "Utilities", "Software", "Hardware", "Marketing", "Travel", "Miscellaneous"], key="exp_category")
            amount = st.number_input("Amount (₹)", min_value=0.0, step=1000.0, key="exp_amount")
            col1, col2 = st.columns(2)
            with col1:
                month_name = st.selectbox("Month", months, index=months.index(datetime.now().strftime('%B')), key="exp_month")
            with col2:
                year = st.selectbox("Year", years, index=years.index(current_year), key="exp_year")
            description = st.text_area("Description", key="exp_description")
            emp_id = None
            if st.button("Add Expense", key="add_expense"):
                if category and amount and month_name and year:
                    month_num = months.index(month_name) + 1
                    month_date = f"{year}-{month_num:02d}-01"
                    execute_query(
                        "INSERT INTO expenses (category, amount, month, description, emp_id) VALUES (?, ?, ?, ?, ?)",
                        (category, amount, month_date, description, emp_id)
                    )
                else:
                    st.error("Please fill all required fields.")

            st.subheader("View/Update/Delete Expenses")
            expenses = fetch_data("SELECT e.*, emp.name FROM expenses e LEFT JOIN employees emp ON e.emp_id = emp.emp_id")
            if not expenses.empty:
                expenses['month'] = pd.to_datetime(expenses['month'])
                edited_df = st.data_editor(expenses, num_rows="dynamic", use_container_width=True, hide_index=False, column_config={
                    "exp_id": st.column_config.NumberColumn("ID", disabled=True),
                    "category": st.column_config.SelectboxColumn("Category", options=["Salary", "Rent", "Utilities", "Software", "Hardware", "Marketing", "Travel", "Miscellaneous"]),
                    "amount": st.column_config.NumberColumn("Amount"),
                    "month": st.column_config.DateColumn("Month"),
                    "description": st.column_config.TextColumn("Description"),
                    "emp_id": st.column_config.NumberColumn("Employee ID"),
                    "name": st.column_config.TextColumn("Employee Name", disabled=True),
                }, key="exp_data_editor")
                if st.button("Update Expenses", key="update_expenses"):
                    for index, row in edited_df.iterrows():
                        execute_query(
                            "UPDATE expenses SET category = ?, amount = ?, month = ?, description = ?, emp_id = ? WHERE exp_id = ?",
                            (row['category'], row['amount'], row['month'].strftime('%Y-%m-%d'), row['description'], row['emp_id'], row['exp_id'])
                        )
                st.subheader("Delete Expenses")
                delete_exp_ids = st.multiselect("Select Expenses to Delete", options=expenses['exp_id'], key="delete_exp_select")
                if st.button("Delete Selected Expenses", key="delete_expenses"):
                    for exp_id in delete_exp_ids:
                        execute_query("DELETE FROM expenses WHERE exp_id = ?", (exp_id,))
            else:
                st.info("No expense data available.")

        with tabs[4]:
            st.subheader("Add Revenue")
            source = st.selectbox("Source", ["Sales", "Services", "Subscriptions", "Investments", "Other"], key="rev_source")
            amount = st.number_input("Amount (₹)", min_value=0.0, step=1000.0, key="rev_amount")
            col1, col2 = st.columns(2)
            with col1:
                month_name = st.selectbox("Month", months, index=months.index(datetime.now().strftime('%B')), key="rev_month")
            with col2:
                year = st.selectbox("Year", years, index=years.index(current_year), key="rev_year")
            description = st.text_area("Description", key="rev_description")
            if st.button("Add Revenue", key="add_revenue"):
                if source and amount and month_name and year:
                    month_num = months.index(month_name) + 1
                    month_date = f"{year}-{month_num:02d}-01"
                    execute_query(
                        "INSERT INTO revenues (source, amount, month, description) VALUES (?, ?, ?, ?)",
                        (source, amount, month_date, description)
                    )
                else:
                    st.error("Please fill all required fields.")

            st.subheader("View/Update/Delete Revenues")
            revenues = fetch_data("SELECT * FROM revenues")
            if not revenues.empty:
                revenues['month'] = pd.to_datetime(revenues['month'])
                edited_df = st.data_editor(revenues, num_rows="dynamic", use_container_width=True, hide_index=False, column_config={
                    "rev_id": st.column_config.NumberColumn("ID", disabled=True),
                    "source": st.column_config.SelectboxColumn("Source", options=["Sales", "Services", "Subscriptions", "Investments", "Other"]),
                    "amount": st.column_config.NumberColumn("Amount"),
                    "month": st.column_config.DateColumn("Month"),
                    "description": st.column_config.TextColumn("Description"),
                }, key="rev_data_editor")
                if st.button("Update Revenues", key="update_revenues"):
                    for index, row in edited_df.iterrows():
                        execute_query(
                            "UPDATE revenues SET source = ?, amount = ?, month = ?, description = ? WHERE rev_id = ?",
                            (row['source'], row['amount'], row['month'].strftime('%Y-%m-%d'), row['description'], row['rev_id'])
                        )
                st.subheader("Delete Revenues")
                delete_rev_ids = st.multiselect("Select Revenues to Delete", options=revenues['rev_id'], key="delete_rev_select")
                if st.button("Delete Selected Revenues", key="delete_revenues"):
                    for rev_id in delete_rev_ids:
                        execute_query("DELETE FROM revenues WHERE rev_id = ?", (rev_id,))
            else:
                st.info("No revenue data available.")

        with tabs[5]:
            st.subheader("Leave Approvals")
            pending_leaves = fetch_data("SELECT l.*, e.name FROM leaves l JOIN employees e ON l.emp_id = e.emp_id WHERE l.status = 'Pending'")
            if not pending_leaves.empty:
                leave_id = st.selectbox("Select Leave Request", options=pending_leaves['leave_id'], 
                                        format_func=lambda x: f"{pending_leaves[pending_leaves['leave_id'] == x]['name'].values[0]} - {pending_leaves[pending_leaves['leave_id'] == x]['type'].values[0]} ({pending_leaves[pending_leaves['leave_id'] == x]['start_date'].values[0]} to {pending_leaves[pending_leaves['leave_id'] == x]['end_date'].values[0]})", 
                                        key="admin_leave_select")
                action = st.selectbox("Action", ["Approved", "Rejected"], key="admin_leave_action")
                if st.button("Submit Action", key="admin_submit_leave_action"):
                    execute_query(
                        "UPDATE leaves SET status = ? WHERE leave_id = ?",
                        (action, leave_id)
                    )
                    st.success(f"Leave request {action}!")
            else:
                st.info("No pending leave requests.")

        st.subheader("Database Reset")
        if st.button("Clear Entire Database", key="clear_database"):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("DROP TABLE IF EXISTS employees")
            c.execute("DROP TABLE IF EXISTS attendance")
            c.execute("DROP TABLE IF EXISTS tasks")
            c.execute("DROP TABLE IF EXISTS expenses")
            c.execute("DROP TABLE IF EXISTS revenues")
            c.execute("DROP TABLE IF EXISTS performance_reviews")
            c.execute("DROP TABLE IF EXISTS leaves")
            conn.commit()
            conn.close()
            init_db()
            st.warning("Database has been cleared and reinitialized!")

elif page == "Attendance Tracking":
    st.header("Attendance Tracking")
    
    col1, col2 = st.columns(2)
    with col1:
        employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
        selected_emp = st.selectbox("Select Employee", options=["All"] + list(employees['name']), key="att_track_emp_select")
    with col2:
        date_filter = st.date_input("Select Date Range", value=(datetime.now().date() - timedelta(days=30), datetime.now().date()), key="att_date_range")
    
    if selected_emp == "All":
        att_df = fetch_data(
            "SELECT a.*, e.name, e.expected_login, e.expected_logout FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE date(login_time) BETWEEN ? AND ?",
            (date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    else:
        emp_id = employees[employees['name'] == selected_emp]['emp_id'].values[0]
        att_df = fetch_data(
            "SELECT a.*, e.name, e.expected_login, e.expected_logout FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE a.emp_id = ? AND date(login_time) BETWEEN ? AND ?",
            (emp_id, date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    
    if not att_df.empty:
        att_df['working_hours'] = att_df.apply(lambda row: calculate_working_hours(row['login_time'], row['logout_time'], row['break_duration']), axis=1)
        att_df['late_min'], att_df['early_min'] = zip(*att_df.apply(
            lambda row: calculate_late_early(row['login_time'], row['expected_login'], row['logout_time'], row['expected_logout']), axis=1))
        
        total_hours = att_df['working_hours'].sum()
        avg_hours = att_df['working_hours'].mean()
        late_count = len(att_df[att_df['late_min'] > 0])
        early_count = len(att_df[att_df['early_min'] > 0])
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Hours", f"{total_hours:.2f}")
        col2.metric("Avg Hours/Day", f"{avg_hours:.2f}")
        col3.metric("Late Arrivals", late_count)
        col4.metric("Early Departures", early_count)
        
        st.dataframe(att_df[['name', 'login_time', 'logout_time', 'break_duration', 'working_hours', 'late_min', 'early_min', 'notes']])
        
        att_df['date'] = pd.to_datetime(att_df['login_time']).dt.date
        daily_hours = att_df.groupby('date')['working_hours'].sum().reset_index()
        fig = px.line(daily_hours, x='date', y='working_hours', title='Attendance Trends: Working Hours per Day')
        st.plotly_chart(fig)
        
        if selected_emp == "All":
            emp_hours = att_df.groupby('name')['working_hours'].sum().reset_index().sort_values('working_hours', ascending=False)
            fig = px.bar(emp_hours, x='name', y='working_hours', title='Total Hours by Employee')
            st.plotly_chart(fig)
    else:
        st.info("No attendance data available for the selected filters.")

elif page == "Productivity Tracking":
    st.header("Productivity Tracking")
    
    col1, col2 = st.columns(2)
    with col1:
        employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
        selected_emp = st.selectbox("Select Employee", options=["All"] + list(employees['name']), key="prod_emp_select")
    with col2:
        date_filter = st.date_input("Select Date Range", value=(datetime.now().date() - timedelta(days=30), datetime.now().date()), key="prod_date_range")
    
    if selected_emp == "All":
        tasks_df = fetch_data(
            "SELECT t.*, e.name FROM tasks t JOIN employees e ON t.emp_id = e.emp_id WHERE date(assigned_date) BETWEEN ? AND ?",
            (date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    else:
        emp_id = employees[employees['name'] == selected_emp]['emp_id'].values[0]
        tasks_df = fetch_data(
            "SELECT t.*, e.name FROM tasks t JOIN employees e ON t.emp_id = e.emp_id WHERE t.emp_id = ? AND date(assigned_date) BETWEEN ? AND ?",
            (emp_id, date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    
    if not tasks_df.empty:
        total_tasks = len(tasks_df)
        completed_tasks = len(tasks_df[tasks_df['status'].str.contains('Completed')])
        on_time = len(tasks_df[tasks_df['status'] == 'Completed On-Time'])
        productivity = (on_time / total_tasks * 100) if total_tasks > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tasks", total_tasks)
        col2.metric("Completed Tasks", completed_tasks)
        col3.metric("On-Time Tasks", on_time)
        col4.metric("Productivity Score", f"{productivity:.2f}%")
        
        st.dataframe(tasks_df[['name', 'task_name', 'description', 'assigned_date', 'due_date', 'submission_date', 'status', 'priority']])
        
        status_counts = tasks_df['status'].value_counts().reset_index()
        status_counts.columns = ['status', 'count']
        fig_pie = px.pie(status_counts, values='count', names='status', title='Task Status Breakdown')
        st.plotly_chart(fig_pie)
        
        priority_counts = tasks_df['priority'].value_counts().reset_index()
        priority_counts.columns = ['priority', 'count']
        fig_priority = px.pie(priority_counts, values='count', names='priority', title='Task Priority Distribution')
        st.plotly_chart(fig_pie)
        
        if selected_emp == "All":
            emp_tasks = tasks_df.groupby('name').agg({
                'task_id': 'count',
                'status': lambda x: (x == 'Completed On-Time').sum()
            }).reset_index()
            emp_tasks.columns = ['name', 'total_tasks', 'on_time_tasks']
            emp_tasks['productivity'] = (emp_tasks['on_time_tasks'] / emp_tasks['total_tasks'] * 100).round(2)
            fig = px.bar(emp_tasks, x='name', y='productivity', title='Productivity by Employee (%)')
            st.plotly_chart(fig)
    else:
        st.info("No tasks data available for the selected filters.")

elif page == "Payroll Calculation":
    st.header("Payroll Calculation")
    
    col1, col2 = st.columns(2)
    with col1:
        month_name = st.selectbox("Month", months, index=months.index(datetime.now().strftime('%B')), key="payroll_month")
    with col2:
        year = st.selectbox("Year", years, index=years.index(current_year), key="payroll_year")
    
    month_num = months.index(month_name) + 1
    month_start = f"{year}-{month_num:02d}-01"
    
    employees = fetch_data("SELECT emp_id, name, department, salary FROM employees WHERE status = 'Active'")
    
    if not employees.empty:
        # Calculate annual salary
        employees['annual_salary'] = employees['salary'] * 12
        
        # Check if salaries for the selected month already exist in expenses
        existing_expenses = fetch_data(
            "SELECT emp_id, amount FROM expenses WHERE category = 'Salary' AND month = ?",
            (month_start,)
        )
        existing_emp_ids = set(existing_expenses['emp_id'].values) if not existing_expenses.empty else set()
        
        # Add salaries to expenses if not already added
        for index, row in employees.iterrows():
            if row['emp_id'] not in existing_emp_ids:
                add_salary_to_expenses(row['emp_id'], row['salary'], month_start, row['name'])
        
        # Fetch salary expenses for the selected month
        payroll_df = fetch_data(
            "SELECT e.emp_id, e.name, e.department, e.salary AS monthly_salary, ex.amount AS expense_salary "
            "FROM employees e "
            "LEFT JOIN expenses ex ON e.emp_id = ex.emp_id AND ex.category = 'Salary' AND ex.month = ? "
            "WHERE e.status = 'Active'",
            (month_start,)
        )
        
        # Ensure monthly_salary is filled; use salary from employees if expense_salary is null
        payroll_df['monthly_salary'] = payroll_df['expense_salary'].combine_first(payroll_df['monthly_salary'])
        
        # Calculate annual salary for display
        payroll_df['annual_salary'] = payroll_df['monthly_salary'] * 12
        
        total_payroll = payroll_df['monthly_salary'].sum() if not payroll_df.empty else 0
        avg_salary = payroll_df['monthly_salary'].mean() if not payroll_df.empty else 0
        
        col1, col2 = st.columns(2)
        col1.metric("Total Payroll", f"₹{total_payroll:,.2f}")
        col2.metric("Average Monthly Salary", f"₹{avg_salary:,.2f}")
        
        st.dataframe(payroll_df[['name', 'department', 'monthly_salary', 'annual_salary']])
        
        fig_bar = px.bar(payroll_df, x='name', y=['monthly_salary'], title='Payroll Summary: Monthly Salary')
        st.plotly_chart(fig_bar)
        
        dept_payroll = payroll_df.groupby('department')['monthly_salary'].sum().reset_index()
        fig_dept = px.pie(dept_payroll, values='monthly_salary', names='department', title='Payroll Distribution by Department')
        st.plotly_chart(fig_dept)
    else:
        st.info("No active employees found.")

elif page == "Expense & Revenue Analysis":
    st.header("Expense & Revenue Analysis")
    
    col1, col2 = st.columns(2)
    with col1:
        month_name = st.selectbox("Month", months, index=months.index(datetime.now().strftime('%B')), key="exp_rev_month")
    with col2:
        year = st.selectbox("Year", years, index=years.index(current_year), key="exp_rev_year")
    
    month_num = months.index(month_name) + 1
    month_start = f"{year}-{month_num:02d}-01"
    next_month = (datetime.strptime(month_start, '%Y-%m-%d') + relativedelta(months=1)).replace(day=1).strftime('%Y-%m-%d')
    
    exp_df = fetch_data("SELECT e.*, emp.name FROM expenses e LEFT JOIN employees emp ON e.emp_id = emp.emp_id WHERE date(e.month) >= ? AND date(e.month) < ?", (month_start, next_month))
    rev_df = fetch_data("SELECT * FROM revenues WHERE date(month) >= ? AND date(month) < ?", (month_start, next_month))
    
    if not exp_df.empty or not rev_df.empty:
        total_expense = exp_df['amount'].sum() if not exp_df.empty else 0
        total_revenue = rev_df['amount'].sum() if not rev_df.empty else 0
        profit = total_revenue - total_expense
        
        st.subheader("Financial Summary")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Expenses", f"₹{total_expense:,.2f}")
        col2.metric("Total Revenue", f"₹{total_revenue:,.2f}")
        col3.metric("Profit", f"₹{profit:,.2f}", delta=f"{(profit/total_revenue*100):.2f}%" if total_revenue > 0 else "N/A")
        
        st.subheader("Minimum Revenue Targets (for 10% Profit Margin)")
        profit_margin = 0.10
        min_monthly_revenue = total_expense / (1 - profit_margin) if total_expense > 0 else 0
        min_weekly_revenue = min_monthly_revenue / 4.33 if min_monthly_revenue > 0 else 0
        min_daily_revenue = min_weekly_revenue / 5 if min_weekly_revenue > 0 else 0
        min_yearly_revenue = min_monthly_revenue * 12 if min_monthly_revenue > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Min Daily Revenue", f"₹{min_daily_revenue:,.2f}")
        col2.metric("Min Weekly Revenue", f"₹{min_weekly_revenue:,.2f}")
        col3.metric("Min Monthly Revenue", f"₹{min_monthly_revenue:,.2f}")
        col4.metric("Min Yearly Revenue", f"₹{min_yearly_revenue:,.2f}")
        
        st.subheader("Average Revenue Metrics (Historical)")
        rev_trend = fetch_data("SELECT month, SUM(amount) as total FROM revenues GROUP BY month ORDER BY month")
        if not rev_trend.empty:
            rev_trend['month'] = pd.to_datetime(rev_trend['month'])
            total_days = (rev_trend['month'].max() - rev_trend['month'].min()).days + 1
            total_revenue_all = rev_trend['total'].sum()
            avg_daily_revenue = total_revenue_all / total_days if total_days > 0 else 0
            avg_weekly_revenue = avg_daily_revenue * 7
            avg_monthly_revenue = avg_daily_revenue * 30
            avg_yearly_revenue = avg_daily_revenue * 365
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Avg Daily Revenue", f"₹{avg_daily_revenue:,.2f}")
            col2.metric("Avg Weekly Revenue", f"₹{avg_weekly_revenue:,.2f}")
            col3.metric("Avg Monthly Revenue", f"₹{avg_monthly_revenue:,.2f}")
            col4.metric("Avg Yearly Revenue", f"₹{avg_yearly_revenue:,.2f}")
        
        st.subheader("Breakdown")
        col1, col2 = st.columns(2)
        with col1:
            if not exp_df.empty:
                exp_breakdown = exp_df.groupby('category')['amount'].sum().reset_index()
                fig_pie_exp = px.pie(exp_breakdown, values='amount', names='category', title='Expense Breakdown')
                st.plotly_chart(fig_pie_exp)
        with col2:
            if not rev_df.empty:
                rev_breakdown = rev_df.groupby('source')['amount'].sum().reset_index()
                fig_pie_rev = px.pie(rev_breakdown, values='amount', names='source', title='Revenue Breakdown')
                st.plotly_chart(fig_pie_rev)
        
        st.subheader("Trend and Predictions")
        exp_trend = fetch_data("SELECT month, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month")
        rev_trend = fetch_data("SELECT month, SUM(amount) as total FROM revenues GROUP BY month ORDER BY month")
        
        if not exp_trend.empty and not rev_trend.empty:
            exp_trend['month'] = pd.to_datetime(exp_trend['month'])
            rev_trend['month'] = pd.to_datetime(rev_trend['month'])
            
            X_exp = np.array(range(len(exp_trend))).reshape(-1, 1)
            y_exp = exp_trend['total'].values.reshape(-1, 1)
            X_rev = np.array(range(len(rev_trend))).reshape(-1, 1)
            y_rev = rev_trend['total'].values.reshape(-1, 1)
            
            poly = PolynomialFeatures(degree=2)
            X_exp_poly = poly.fit_transform(X_exp)
            X_rev_poly = poly.fit_transform(X_rev)
            
            model_exp = LinearRegression()
            model_rev = LinearRegression()
            model_exp.fit(X_exp_poly, y_exp)
            model_rev.fit(X_rev_poly, y_rev)
            
            future_X = np.array(range(len(exp_trend), len(exp_trend) + 3)).reshape(-1, 1)
            future_X_poly = poly.transform(future_X)
            pred_exp = model_exp.predict(future_X_poly)
            pred_rev = model_rev.predict(future_X_poly)
            
            exp_dates = pd.date_range(start=exp_trend['month'].min(), periods=len(exp_trend) + 3, freq='MS')
            rev_dates = pd.date_range(start=rev_trend['month'].min(), periods=len(rev_trend) + 3, freq='MS')
            exp_data = np.concatenate((exp_trend['total'], pred_exp.flatten()))
            rev_data = np.concatenate((rev_trend['total'], pred_rev.flatten()))
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=exp_dates, y=exp_data, mode='lines+markers', name='Expenses', line=dict(dash='solid')))
            fig.add_trace(go.Scatter(x=rev_dates, y=rev_data, mode='lines+markers', name='Revenue', line=dict(dash='solid')))
            fig.add_trace(go.Scatter(x=exp_dates[-3:], y=exp_data[-3:], mode='markers', name='Expense Prediction', marker=dict(size=10, symbol='diamond')))
            fig.add_trace(go.Scatter(x=rev_dates[-3:], y=rev_data[-3:], mode='markers', name='Revenue Prediction', marker=dict(size=10, symbol='diamond')))
            fig.update_layout(title='Expense & Revenue Trend with Prediction (Next 3 Months)', xaxis_title='Month', yaxis_title='Amount (₹)')
            st.plotly_chart(fig)
        
        st.subheader("AI-Powered Revenue Insights")
        if not rev_trend.empty:
            avg_monthly_price = avg_monthly_revenue / 100 if avg_monthly_revenue > 0 else 100
            user_data = {
                "price": avg_monthly_price,
                "age": 35,
                "income": 50000,
                "trial_used": 1,
                "marketing_channel": rev_df['source'].mode()[0] if not rev_df.empty and 'source' in rev_df else "Subscriptions"
            }
            predicted_prob = min(total_revenue / (min_monthly_revenue * 1.5) if min_monthly_revenue > 0 else 0.5, 1.0)
            
            with st.spinner("Fetching AI insights..."):
                insights = get_grok_insights(user_data, predicted_prob)
            if insights['error']:
                st.error(f"AI Insights Error: {insights['error']}")
            else:
                st.write("**Recommendations for Subscription Optimization:**")
                for rec in insights['recommendations']:
                    if rec.strip():
                        st.write(rec)
        else:
            st.info("No revenue data available for AI analysis.")
    else:
        st.info("No expense or revenue data available for the selected month.")

elif page == "Performance Reviews":
    st.header("Performance Reviews")
    
    col1, col2 = st.columns(2)
    with col1:
        employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
        selected_emp = st.selectbox("Select Employee", options=["All"] + list(employees['name']), key="perf_emp_select")
    with col2:
        date_filter = st.date_input("Select Date Range", value=(datetime.now().date() - timedelta(days=365), datetime.now().date()), key="perf_date_range")
    
    if selected_emp == "All":
        reviews_df = fetch_data(
            "SELECT pr.*, e.name FROM performance_reviews pr JOIN employees e ON pr.emp_id = e.emp_id WHERE date(review_date) BETWEEN ? AND ?",
            (date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    else:
        emp_id = employees[employees['name'] == selected_emp]['emp_id'].values[0]
        reviews_df = fetch_data(
            "SELECT pr.*, e.name FROM performance_reviews pr JOIN employees e ON pr.emp_id = e.emp_id WHERE pr.emp_id = ? AND date(review_date) BETWEEN ? AND ?",
            (emp_id, date_filter[0].strftime('%Y-%m-%d'), date_filter[1].strftime('%Y-%m-%d'))
        )
    
    if not reviews_df.empty:
        reviews_df['review_date'] = pd.to_datetime(reviews_df['review_date'])
        
        avg_rating = reviews_df['rating'].mean()
        total_reviews = len(reviews_df)
        high_rated = len(reviews_df[reviews_df['rating'] >= 4])
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Average Rating", f"{avg_rating:.2f}/5")
        col2.metric("Total Reviews", total_reviews)
        col3.metric("High Ratings (4+)", high_rated)
        
        st.dataframe(reviews_df[['name', 'review_date', 'rating', 'comments', 'reviewer']])
        
        if selected_emp == "All":
            fig = px.line(reviews_df, x='review_date', y='rating', color='name', title='Performance Rating Trend')
        else:
            fig = px.line(reviews_df, x='review_date', y='rating', title=f'Performance Rating Trend for {selected_emp}')
        st.plotly_chart(fig)
        
        rating_counts = reviews_df['rating'].value_counts().reset_index()
        rating_counts.columns = ['rating', 'count']
        fig_dist = px.bar(rating_counts, x='rating', y='count', title='Rating Distribution')
        st.plotly_chart(fig_dist)
        
        with st.expander("Add New Review"):
            emp_id = st.selectbox("Select Employee for Review", options=employees['emp_id'], format_func=lambda x: employees[employees['emp_id'] == x]['name'].values[0], key="perf_review_emp")
            review_date = st.date_input("Review Date", value=datetime.now().date(), key="perf_review_date")
            rating = st.slider("Rating (1-5)", 1, 5, 3, key="perf_rating")
            comments = st.text_area("Comments", key="perf_comments")
            reviewer = st.text_input("Reviewer", key="perf_reviewer")
            if st.button("Submit Review", key="add_review"):
                if emp_id and review_date and rating and reviewer:
                    execute_query(
                        "INSERT INTO performance_reviews (emp_id, review_date, rating, comments, reviewer) VALUES (?, ?, ?, ?, ?)",
                        (emp_id, review_date.strftime('%Y-%m-%d'), rating, comments, reviewer)
                    )
                else:
                    st.error("Please fill all required fields.")
    else:
        st.info("No performance reviews available for the selected filters.")

elif page == "Leave Management":
    st.header("Leave Management")
    
    col1, col2 = st.columns(2)
    with col1:
        employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
        selected_emp = st.selectbox("Select Employee", options=["All"] + list(employees['name']), key="leave_emp_select")
    with col2:
        status_filter = st.selectbox("Status Filter", ["All", "Pending", "Approved", "Rejected"], key="leave_status_filter")
    
    query = "SELECT l.*, e.name FROM leaves l JOIN employees e ON l.emp_id = e.emp_id"
    params = []
    if selected_emp != "All":
        emp_id = employees[employees['name'] == selected_emp]['emp_id'].values[0]
        query += " WHERE l.emp_id = ?"
        params.append(emp_id)
    if status_filter != "All":
        query += " AND l.status = ?" if selected_emp != "All" else " WHERE l.status = ?"
        params.append(status_filter)
    
    leaves_df = fetch_data(query, params) if params else fetch_data(query)
    
    if not leaves_df.empty:
        leaves_df['start_date'] = pd.to_datetime(leaves_df['start_date'])
        leaves_df['end_date'] = pd.to_datetime(leaves_df['end_date'])
        leaves_df['duration'] = (leaves_df['end_date'] - leaves_df['start_date']).dt.days + 1
        
        total_leaves = len(leaves_df)
        pending_leaves = len(leaves_df[leaves_df['status'] == 'Pending'])
        approved_leaves = len(leaves_df[leaves_df['status'] == 'Approved'])
        total_leave_days = leaves_df['duration'].sum()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Leave Requests", total_leaves)
        col2.metric("Pending Requests", pending_leaves)
        col3.metric("Approved Requests", approved_leaves)
        col4.metric("Total Leave Days", total_leave_days)
        
        st.dataframe(leaves_df[['name', 'start_date', 'end_date', 'duration', 'type', 'status', 'reason']])
        
        leave_types = leaves_df['type'].value_counts().reset_index()
        leave_types.columns = ['type', 'count']
        fig_types = px.pie(leave_types, values='count', names='type', title='Leave Type Distribution')
        st.plotly_chart(fig_types)
        
        leave_status = leaves_df['status'].value_counts().reset_index()
        leave_status.columns = ['status', 'count']
        fig_status = px.pie(leave_status, values='count', names='status', title='Leave Status Distribution')
        st.plotly_chart(fig_status)
        
    else:
        st.info("No leave data available for the selected filters.")
    
    st.subheader("Request New Leave")
    employees = fetch_data("SELECT emp_id, name FROM employees WHERE status = 'Active'")
    if not employees.empty:
        emp_id = st.selectbox("Select Employee", options=employees['emp_id'], format_func=lambda x: employees[employees['emp_id'] == x]['name'].values[0], key="leave_emp")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", key="leave_start_date")
        with col2:
            end_date = st.date_input("End Date", key="leave_end_date")
        leave_type = st.selectbox("Leave Type", ["Sick", "Casual", "Annual", "Maternity", "Paternity"], key="leave_type")
        reason = st.text_area("Reason", key="leave_reason")
        if st.button("Submit Leave Request", key="add_leave"):
            if emp_id and start_date and end_date and leave_type:
                if start_date <= end_date:
                    execute_query(
                        "INSERT INTO leaves (emp_id, start_date, end_date, type, reason) VALUES (?, ?, ?, ?, ?)",
                        (emp_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), leave_type, reason)
                    )
                    name = employees[employees['emp_id'] == emp_id]['name'].values[0]
                    notify_admin_leave_request(name, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), leave_type, reason)
                    st.success("Leave request submitted! Admin has been notified.")
                else:
                    st.error("End date must be after start date.")
            else:
                st.error("Please fill all required fields.")
    else: 
        st.info("No active employees found. Add employees first.")