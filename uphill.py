import os
import csv
from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from sqlalchemy.exc import OperationalError
from fpdf import FPDF
from datetime import datetime
import PyPDF2
import pytesseract
from PIL import Image
import docx
import requests
import json

app = Flask(__name__)
# IMPORTANT: In a production environment, use a strong, randomly generated secret key
app.secret_key = "your_secret_key_change_this_in_production"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/uploads" # Ensure this folder exists and is writable
app.config["PRESCRIPTION_FOLDER"] = "static/prescriptions" # New folder for prescriptions

# Ensure upload directories exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["PRESCRIPTION_FOLDER"], exist_ok=True) # Create prescriptions folder

# Initialize SQLAlchemy with the Flask app
db = SQLAlchemy(app)

# User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(200), default="default.jpg") # Default profile picture
    registration_date = db.Column(db.DateTime, default=datetime.utcnow) # Automatically set registration date

# Appointment Model
class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(50), nullable=False)
    time = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='Pending') # Added status for appointments
    # Establishes a relationship with the User model, allowing access to appointment.user
    user = db.relationship('User', backref=db.backref('appointments', lazy=True))

# Video Consultation Model
class VideoConsultation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(50), nullable=False)
    time = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='Scheduled') # E.g., 'Scheduled', 'Completed', 'Cancelled'
    meeting_link = db.Column(db.String(200)) # Unique link for the video call
    # Establishes a relationship with the User model, allowing access to video_consultation.user
    user = db.relationship('User', backref=db.backref('video_consultations', lazy=True))

# --- NEW: Medicine Model ---
class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    dosage = db.Column(db.String(50)) # e.g., "500mg", "10mg"
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(200), default="default_medicine.jpg") # Path to medicine image

# --- NEW: Prescription Model ---
class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prescription_path = db.Column(db.String(200), nullable=False) # Path to the uploaded prescription file
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending Review') # e.g., 'Pending Review', 'Approved', 'Rejected', 'Filled'
    notes = db.Column(db.Text) # Any notes from pharmacist or AI analysis
    user = db.relationship('User', backref=db.backref('prescriptions', lazy=True))

# --- NEW: Order Model ---
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='Pending') # e.g., 'Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled'
    delivery_address = db.Column(db.Text, nullable=False)
    user = db.relationship('User', backref=db.backref('orders', lazy=True))
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan") # Link to order items

# --- NEW: OrderItem Model ---
class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_order = db.Column(db.Float, nullable=False) # Price at the time of order
    medicine = db.relationship('Medicine', backref=db.backref('order_items', lazy=True))

# Helper function for sending messages (placeholder)
def send_user_message(user_id, message):
    """
    Placeholder function for sending a message/notification to a user.
    In a real application, this would integrate with an email service,
    SMS gateway, or an in-app notification system.
    """
    user = User.query.get(user_id)
    if user:
        print(f"--- Notification to {user.username} (ID: {user_id}) ---")
        print(f"Message: {message}")
        print("------------------------------------------")
    else:
        print(f"Could not find user with ID {user_id} to send message.")

# Function to create database and add missing columns if they don't exist
def create_database():
    with app.app_context():
        # Create all tables defined by SQLAlchemy models if they don't exist
        db.create_all()
        # Check and add 'profile_pic' column if missing (for existing databases)
        try:
            db.session.execute(db.text("SELECT profile_pic FROM user LIMIT 1"))
        except OperationalError:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN profile_pic TEXT DEFAULT 'default.jpg'"))
            db.session.commit()
        # Check and add 'registration_date' column if missing (for existing databases)
        try:
            db.session.execute(db.text("SELECT registration_date FROM user LIMIT 1"))
        except OperationalError:
            # For existing users, this column will be NULL; consider updating them or handling NULLs
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN registration_date DATETIME"))
            db.session.commit()
        # Check and add 'status' column to Appointment if missing
        try:
            db.session.execute(db.text("SELECT status FROM appointment LIMIT 1"))
        except OperationalError:
            db.session.execute(db.text("ALTER TABLE appointment ADD COLUMN status TEXT DEFAULT 'Pending'"))
            db.session.commit()
            print("Added 'status' column to 'Appointment' table.")
        
        # --- NEW: Populate some sample medicines if the table is empty ---
        if Medicine.query.count() == 0:
            print("Adding sample medicines...")
            sample_medicines = [
                Medicine(name="Paracetamol", dosage="500mg", price=10.50, stock=100, description="Pain reliever and fever reducer."),
                Medicine(name="Amoxicillin", dosage="250mg", price=25.00, stock=50, description="Antibiotic for bacterial infections."),
                Medicine(name="Omeprazole", dosage="20mg", price=15.75, stock=75, description="Reduces stomach acid."),
                Medicine(name="Cetirizine", dosage="10mg", price=8.20, stock=120, description="Antihistamine for allergy relief."),
                Medicine(name="Ibuprofen", dosage="200mg", price=12.00, stock=90, description="NSAID for pain and inflammation.")
            ]
            db.session.add_all(sample_medicines)
            db.session.commit()
            print("Sample medicines added.")

# ---- File Text Extraction ----
def extract_text_from_file(file_stream, original_filename):
    file_ext = os.path.splitext(original_filename)[1].lower()
    text = ""
    try:
        if file_ext == '.pdf':
            reader = PyPDF2.PdfReader(file_stream)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
            image = Image.open(file_stream)
            text = pytesseract.image_to_string(image)
        elif file_ext in ['.doc', '.docx']:
            doc = docx.Document(file_stream)
            text = "\n".join([para.text for para in doc.paragraphs])
        elif file_ext == '.txt':
            text = file_stream.read().decode('utf-8')
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")
    except Exception as e:
        raise Exception(f"Failed to extract text from file ({file_ext}): {str(e)}. Ensure Tesseract OCR is installed for images and that file is not corrupted.")
    return text

# ---- Gemini API Integration ----
def query_llm(health_data, symptoms):
    # Gemini API setup (using gemini-2.0-flash model as per Canvas guidelines)
    # The API key will be provided by the Canvas environment when apiKey is an empty string.
    apiKey = "AIzaSyAKmXWLt4K_LwfgbSGMjxqCWl7jtcnta4E" # This is a placeholder key. In a real application, keep keys secure.
    apiUrl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={apiKey}"

    chat_history = []
    
    # Construct the prompt for the LLM
    prompt_text = f"""
    You are a medical analysis assistant. Analyze the following health report data and symptoms to identify possible medical conditions and suggest appropriate medicines or treatments. Provide a concise response with:
    - Possible condition(s)
    - Suggested medicines or treatments (if applicable)
    - A disclaimer that this is not a substitute for professional medical advice.

    Health Report Data: {health_data}
    Symptoms: {symptoms}

    Format the response as:
    Condition: [condition]
    Suggestions: [medicines or treatments]
    Disclaimer: Always consult a healthcare professional for accurate diagnosis and treatment.
    """
    
    chat_history.append({
        "role": "user",
        "parts": [{"text": prompt_text}]
    })

    payload = {
        "contents": chat_history,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "condition": {"type": "STRING"},
                    "suggestions": {"type": "STRING"},
                    "disclaimer": {"type": "STRING"}
                },
                "required": ["condition", "suggestions", "disclaimer"]
            }
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(apiUrl, headers=headers, data=json.dumps(payload))
        response.raise_for_status()

        result = response.json()
        
        if (result.get("candidates") and len(result["candidates"]) > 0 and
            result["candidates"][0].get("content") and result["candidates"][0]["content"].get("parts") and
            len(result["candidates"][0]["content"]["parts"]) > 0):
            
            json_string = result["candidates"][0]["content"]["parts"][0]["text"]
            parsed_json = json.loads(json_string)
            
            condition = parsed_json.get("condition", "Not identified")
            suggestions = parsed_json.get("suggestions", "Consult a doctor for recommendations")
            disclaimer = parsed_json.get("disclaimer", "Always consult a healthcare professional for accurate diagnosis and treatment.")
            
            return {
                "condition": condition,
                "suggestions": suggestions,
                "disclaimer": disclaimer
            }
        else:
            print(f"Unexpected Gemini API response structure: {result}")
            raise Exception("Unexpected response from AI service: Invalid structure.")

    except requests.exceptions.RequestException as e:
        print(f"Gemini API request failed: {e}")
        raise Exception(f"Failed to get analysis from AI service: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from Gemini API: {e}. Raw response: {response.text}")
        raise Exception("Invalid JSON response from AI service.")
    except Exception as e:
        print(f"An unexpected error occurred during Gemini API query: {e}")
        raise Exception(f"An unexpected error occurred during AI analysis: {str(e)}")

# ---- Health Analysis API ----
@app.route("/api/analyze-health", methods=["POST"])
def analyze_health():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        file = request.files.get('health-report')
        symptoms = request.form.get('symptoms')
        if not file or not symptoms:
            return jsonify({"error": "Missing input"}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        with open(file_path, 'rb') as f_stream:
            health_data = extract_text_from_file(f_stream, filename)

        analysis = query_llm(health_data, symptoms)
        os.remove(file_path)
        return jsonify({
            "filename": filename,
            "symptoms": symptoms,
            "condition": analysis["condition"],
            "suggestions": analysis["suggestions"],
            "disclaimer": analysis["disclaimer"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return redirect(url_for("home"))

@app.route("/home")
def home():
    return render_template("Home.html")

@app.route("/home18")
def home18():
    return render_template("Home18.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["user"] = user.username
            session["email"] = user.email
            session["profile_pic"] = user.profile_pic
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid credentials. Try again!")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return render_template("signup.html", error="Email already exists. Try logging in!")

        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/dashboard")
def dashboard():
    if "user" in session:
        user = User.query.filter_by(username=session["user"]).first()
        appointments = Appointment.query.filter_by(user_id=user.id).order_by(Appointment.date.desc()).all()
        video_consultations = VideoConsultation.query.filter_by(user_id=user.id).order_by(VideoConsultation.date.desc()).all()
        
        # Fetch prescriptions and orders for dashboard
        prescriptions = Prescription.query.filter_by(user_id=user.id).order_by(Prescription.upload_date.desc()).all()
        orders = Order.query.filter_by(user_id=user.id).order_by(Order.order_date.desc()).all()

        return render_template(
            "dashboard.html", 
            username=session["user"], 
            email=session["email"], 
            profile_pic=session["profile_pic"], 
            appointments=appointments,
            video_consultations=video_consultations,
            prescriptions=prescriptions,
            orders=orders
        )
    return redirect(url_for("login"))

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["user"]).first()

    if request.method == "POST":
        user.username = request.form["username"]
        user.email = request.form["email"]

        if "profile_pic" in request.files:
            file = request.files["profile_pic"]
            if file.filename != "":
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(file_path)
                user.profile_pic = filename
                session["profile_pic"] = filename

        if request.form["password"]:
            user.password = generate_password_hash(request.form["password"], method="pbkdf2:sha256")

        db.session.commit()
        session["user"] = user.username
        session["email"] = user.email

        return redirect(url_for("profile"))

    return render_template("profile.html", username=user.username, email=user.email, profile_pic=user.profile_pic)

@app.route("/reports")
def reports():
    if "user" in session:
        return render_template("reports.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

@app.route("/login_aboutus")
def login_aboutus():
    # You might want to add a check for manager_logged_in here if this page is exclusive to managers
    # if not session.get("manager_logged_in"):
    #     flash("Unauthorized access.", "danger")
    #     return redirect(url_for("login"))
    return render_template("login_aboutus.html", datetime=datetime)

@app.route("/download_csv")
def download_csv():
    csv_file = "static/reports.csv"
    with open(csv_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Date", "Heart Rate (BPM)", "Steps", "Sleep (Hours)"])
        writer.writerow(["2025-06-21", "70", "10000", "7.0"])
    return send_file(csv_file, as_attachment=True, mimetype='text/csv', download_name='health_report.csv')

@app.route("/download_pdf")
def download_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Comprehensive Medical Report", ln=True, align="C")
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Patient Information:", ln=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 5, f"Name: John Doe", ln=True)
    pdf.cell(0, 5, f"Date of Birth: 1990-05-15", ln=True)
    pdf.cell(0, 5, f"Report Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Key Vitals & Metrics:", ln=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(40, 10, "Date", 1)
    pdf.cell(50, 10, "Heart Rate (BPM)", 1)
    pdf.cell(40, 10, "Steps", 1)
    pdf.cell(40, 10, "Sleep (Hours)", 1)
    pdf.ln()
    
    pdf.cell(40, 10, "2025-06-21", 1)
    pdf.cell(50, 10, "70", 1)
    pdf.cell(40, 10, "10000", 1)
    pdf.cell(40, 10, "7.0", 1)
    pdf.ln()
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Medical History Summary:", ln=True)
    pdf.set_font("Arial", '', 10)
    medical_history = "Patient has a history of seasonal allergies, well-managed with over-the-counter antihistamines. No significant surgical history. Family history includes hypertension on paternal side."
    pdf.multi_cell(0, 5, medical_history)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Presenting Symptoms (Self-Reported):", ln=True)
    pdf.set_font("Arial", '', 10)
    symptoms_text = "Occasional fatigue, mild headaches, and intermittent joint stiffness, especially in the mornings. No fever or acute pain reported."
    pdf.multi_cell(0, 5, symptoms_text)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Preliminary AI Analysis:", ln=True)
    pdf.set_font("Arial", '', 10)
    ai_condition = "Based on the provided metrics and self-reported symptoms, a mild inflammatory response could be present, or symptoms consistent with early signs of general fatigue and musculoskeletal strain. Differential diagnosis might include mild arthritis or a vitamin deficiency."
    ai_suggestions = "Monitor sleep patterns and activity levels. Consider blood tests for inflammatory markers (e.g., CRP, ESR) and vitamin D levels. Maintain a balanced diet and regular hydration. Gentle exercise and stretching are recommended. Consult a physician for further diagnostic testing."
    ai_disclaimer = "This AI analysis is for informational purposes only and should not be considered medical advice. Always consult a qualified healthcare professional for diagnosis and treatment."
    
    pdf.multi_cell(0, 5, f"Possible Condition(s): {ai_condition}")
    pdf.multi_cell(0, 5, f"Suggested Medicines/Treatments: {ai_suggestions}")
    pdf.multi_cell(0, 5, f"Disclaimer: {ai_disclaimer}")
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Doctor's Notes & Recommendations:", ln=True)
    pdf.set_font("Arial", '', 10)
    doctors_notes = "Patient's general health profile appears stable. The reported symptoms are non-specific and could indicate various mild conditions. Further investigation with laboratory tests (as suggested by AI analysis) is advisable to rule out underlying issues. Patient advised to return for follow-up after tests. Maintain current medication regimen if applicable."
    pdf.multi_cell(0, 5, doctors_notes)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, "Electronically Signed by: Dr. A.I. Doctor, Uphill Health", 0, 1, 'C')

    pdf_file = "static/reports.pdf"
    pdf.output(pdf_file)
    return send_file(pdf_file, as_attachment=True, mimetype='application/pdf', download_name='comprehensive_health_report.pdf')

@app.route("/settings")
def settings():
    if "user" in session:
        return render_template("settings.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

@app.route("/about")
def about_us():
    # You might want to pass user info if your header/footer needs it
    if "user" in session:
        return render_template("about_us.html", username=session["user"], profile_pic=session["profile_pic"])
    return render_template("about_us.html") # For non-logged-in users

@app.route("/services")
def services():
    if "user" in session:
        return render_template("services.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

# --- MOVED THIS ROUTE UP HERE ---
@app.route("/upload-prescription", methods=["GET", "POST"])
def upload_prescription():
    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["user"]).first()
    # Fetch user's prescriptions to display on the page
    user_prescriptions = Prescription.query.filter_by(user_id=user.id).order_by(Prescription.upload_date.desc()).all()

    if request.method == "POST":
        if 'prescription_file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        
        file = request.files['prescription_file']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg'}
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        
        if file_ext not in allowed_extensions:
            flash('Invalid file type. Allowed: PDF, JPG, PNG.', 'danger')
            return redirect(request.url)

        if file:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['PRESCRIPTION_FOLDER'], filename)
            file.save(file_path)

            new_prescription = Prescription(
                user_id=user.id,
                prescription_path=filename, # Store just the filename, relative to PRESCRIPTION_FOLDER
                status="Pending Review"
            )
            db.session.add(new_prescription)
            db.session.commit()
            flash('Prescription uploaded successfully. It is pending review by a pharmacist.', 'success')
            return redirect(url_for("dashboard")) # Redirect to dashboard to see uploaded prescription

    return render_template("upload_prescription.html",
                           username=session["user"], 
                           email=session["email"], 
                           profile_pic=session["profile_pic"],
                           prescriptions=user_prescriptions) # Pass prescriptions to the template

@app.route("/ai-risk-analysis")
def ai_risk_analysis():
    if "user" in session:
        return render_template("ai_risk_analysis.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

@app.route("/ecg-monitoring")
def ecg_monitoring():
    if "user" in session:
        return render_template("ecg_monitoring.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

@app.route("/video-consultation", methods=["GET", "POST"])
def video_consultation():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        doctor = request.form["doctor"]
        date = request.form["date"]
        time = request.form["time"]

        user = User.query.filter_by(username=session["user"]).first()
        new_consultation = VideoConsultation(
            user_id=user.id,
            doctor=doctor,
            date=date,
            time=time,
            status="Scheduled",
            meeting_link=f"https://meet.uphillhealth.com/{user.id}-{datetime.now().timestamp()}"
        )
        db.session.add(new_consultation)
        db.session.commit()
        flash(f"Video consultation with {doctor} scheduled for {date} at {time}. Meeting Link: {new_consultation.meeting_link}", "success")
        return redirect(url_for("dashboard")) # Redirect to dashboard to show all bookings

    return render_template("video_consultation.html", 
                           username=session["user"], 
                           email=session["email"], 
                           profile_pic=session["profile_pic"],datetime=datetime)

@app.route("/appointment-booking", methods=["GET", "POST"])
def appointment_booking():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        doctor = request.form["doctor"]
        location = request.form["location"]
        date = request.form["date"]
        time = request.form["time"]

        user = User.query.filter_by(username=session["user"]).first()
        new_appointment = Appointment(
            user_id=user.id,
            doctor=doctor,
            location=location,
            date=date,
            time=time,
            status="Pending" # Default status for new appointments
        )
        db.session.add(new_appointment)
        db.session.commit()
        flash(f"Appointment booked with {doctor} at {location} on {date} at {time}.", "success")
        return redirect(url_for("dashboard")) # Redirect to dashboard to show all bookings

    return render_template("appointment_booking.html", 
                           username=session["user"], 
                           email=session["email"], 
                           profile_pic=session["profile_pic"],datetime=datetime)

@app.route("/cancel-appointment/<int:appointment_id>", methods=["POST"])
def cancel_appointment(appointment_id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized access. Please log in."}), 401

    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.user_id != session["user_id"]:
        return jsonify({"success": False, "message": "Unauthorized: This appointment does not belong to you."}), 403

    # For user-initiated cancellation, directly delete
    db.session.delete(appointment)
    db.session.commit()
    flash("Appointment cancelled successfully.", "info")
    return jsonify({"success": True, "message": "Appointment cancelled successfully"})

@app.route("/cancel-consultation/<int:consultation_id>", methods=["POST"])
def cancel_consultation(consultation_id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized access. Please log in."}), 401

    consultation = VideoConsultation.query.get_or_404(consultation_id)
    if consultation.user_id != session["user_id"]:
        return jsonify({"success": False, "message": "Unauthorized: This consultation does not belong to you."}), 403

    db.session.delete(consultation)
    db.session.commit()
    flash("Video consultation cancelled successfully.", "info")
    return jsonify({"success": True, "message": "Consultation cancelled successfully"})

@app.route("/data-security")
def data_security():
    if "user" in session:
        return render_template("data_security.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"])
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user", None)
    session.pop("email", None)
    session.pop("profile_pic", None)
    return redirect(url_for("login"))

# --- NEW: Medicines Listing Page ---
@app.route("/medicines")
def medicines():
    if "user" not in session:
        return redirect(url_for("login"))
    
    available_medicines = Medicine.query.all()
    return render_template("medicines.html", 
                           username=session["user"], 
                           email=session["email"], 
                           profile_pic=session["profile_pic"],
                           medicines=available_medicines)

# --- NEW: Order Medicine (simplified for direct order) ---
@app.route("/order-medicine/<int:medicine_id>", methods=["POST"])
def order_medicine(medicine_id):
    if "user" not in session:
        flash("Please log in to order medicines.", "warning")
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["user"]).first()
    medicine = Medicine.query.get_or_404(medicine_id)
    quantity = int(request.form.get("quantity", 1)) # Default to 1 if not specified

    if quantity <= 0:
        flash("Quantity must be at least 1.", "danger")
        return redirect(url_for("medicines"))

    if medicine.stock < quantity:
        flash(f"Not enough {medicine.name} in stock. Available: {medicine.stock}", "danger")
        return redirect(url_for("medicines"))

    # For simplicity, we're assuming a fixed delivery address or fetching from user profile
    # In a real app, you'd have a form for delivery details.
    # You might want to fetch this from a 'user.address' field or a separate form.
    delivery_address = "User's Registered Address (Placeholder: Update in profile logic later)"
    # Example: If you add an an address field to User model:
    # if user.address:
    #    delivery_address = user.address
    # else:
    #    flash("Please update your profile with a delivery address.", "danger")
    #    return redirect(url_for("profile"))

    try:
        # Create a new order
        new_order = Order(
            user_id=user.id,
            total_amount=medicine.price * quantity,
            delivery_address=delivery_address,
            status="Pending" # Initial status
        )
        db.session.add(new_order)
        db.session.flush() # Get the ID for new_order before committing

        # Create an order item
        order_item = OrderItem(
            order_id=new_order.id,
            medicine_id=medicine.id,
            quantity=quantity,
            price_at_order=medicine.price
        )
        db.session.add(order_item)

        # Deduct from stock
        medicine.stock -= quantity
        db.session.commit()
        flash(f"Successfully ordered {quantity} of {medicine.name}. Order ID: {new_order.id}", "success")
        return redirect(url_for("dashboard")) # Redirect to dashboard to see order history
    except Exception as e:
        db.session.rollback()
        flash(f"Error placing order: {str(e)}", "danger")
        return redirect(url_for("medicines"))

# --- NEW: View Prescription File ---
@app.route("/view-prescription/<filename>")
def view_prescription(filename):
    if "user" not in session:
        return redirect(url_for("login"))
    
    # Basic security check: ensure the file exists and is in the correct directory
    # For a real app, you'd verify if the logged-in user owns this prescription
    full_path = os.path.join(app.config["PRESCRIPTION_FOLDER"], filename)
    if not os.path.exists(full_path):
        flash("File not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Optional: Check if the user is authorized to view this specific prescription
    # prescription = Prescription.query.filter_by(user_id=session["user_id"], prescription_path=filename).first()
    # if not prescription:
    #     flash("You are not authorized to view this prescription.", "danger")
    #     return redirect(url_for("dashboard"))

    return send_file(full_path, as_attachment=False)

# --- NEW: Order History Page ---
@app.route("/order-history")
def order_history():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(username=session["user"]).first()
    # Fetch orders and their associated items
    user_orders = Order.query.filter_by(user_id=user.id).options(
        db.joinedload(Order.order_items).joinedload(OrderItem.medicine)
    ).order_by(Order.order_date.desc()).all()

    return render_template("order_history.html",
                           username=session["user"], 
                           email=session["email"], 
                           profile_pic=session["profile_pic"],
                           orders=user_orders)
@app.route("/view_orders")
def view_orders():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]
    orders = Order.query.filter_by(user_id=user_id).order_by(Order.order_date.desc()).all()
    return render_template("view_orders.html", orders=orders, username=session["user"], profile_pic=session["profile_pic"])

# --- NEW: Management Login and Dashboard ---

# Hardcoded credentials for management login (for development purposes)
MANAGEMENT_USERNAME = "Pranikov"
MANAGEMENT_PASSWORD = "Spectra@07" # In a real app, hash this password!

@app.route("/management-login", methods=["GET", "POST"])
def management_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == MANAGEMENT_USERNAME and password == MANAGEMENT_PASSWORD:
            session["manager_logged_in"] = True
            flash("Management login successful!", "success")
            return redirect(url_for("management_dashboard"))
        else:
            flash("Invalid management credentials.", "danger")
            return render_template("management_login.html", error="Invalid credentials.")
    return render_template("management_login.html")

# Add this function to your uphill.py file, typically after your model definitions.

@app.route("/management_dashboard", methods=["GET"])
def management_dashboard():
    # Ensure the user is logged in as a manager.
    if not session.get("manager_logged_in"):
        flash("Unauthorized access. Please log in as a manager.", "danger")
        return redirect(url_for("management_login"))

    # Get filter parameters from the request query string
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    start_time_str = request.args.get("start_time")
    end_time_str = request.args.get("end_time")

    # Initialize queries
    appointments_query = db.session.query(Appointment, User).join(User)
    video_consultations_query = db.session.query(VideoConsultation, User).join(User)
    orders_query = Order.query
    prescriptions_query = db.session.query(Prescription, User).join(User)

    # Apply date filters
    if start_date_str:
        appointments_query = appointments_query.filter(Appointment.date >= start_date_str)
        video_consultations_query = video_consultations_query.filter(VideoConsultation.date >= start_date_str)
        orders_query = orders_query.filter(db.func.date(Order.order_date) >= start_date_str)
        prescriptions_query = prescriptions_query.filter(db.func.date(Prescription.upload_date) >= start_date_str)

    if end_date_str:
        appointments_query = appointments_query.filter(Appointment.date <= end_date_str)
        video_consultations_query = video_consultations_query.filter(VideoConsultation.date <= end_date_str)
        orders_query = orders_query.filter(db.func.date(Order.order_date) <= end_date_str)
        prescriptions_query = prescriptions_query.filter(db.func.date(Prescription.upload_date) <= end_date_str)
    
    # Apply time filters
    # For Appointment and VideoConsultation, 'time' is stored as a string like "HH:MM"
    # For Order and Prescription, 'order_date' and 'upload_date' are DateTime objects
    if start_time_str:
        # For string time fields (Appointment, VideoConsultation): direct string comparison
        appointments_query = appointments_query.filter(Appointment.time >= start_time_str)
        video_consultations_query = video_consultations_query.filter(VideoConsultation.time >= start_time_str)
        
        # For DateTime fields (Order, Prescription): use strftime to extract HH:MM string for comparison
        orders_query = orders_query.filter(db.func.strftime('%H:%M', Order.order_date) >= start_time_str)
        prescriptions_query = prescriptions_query.filter(db.func.strftime('%H:%M', Prescription.upload_date) >= start_time_str)

    if end_time_str:
        # For string time fields (Appointment, VideoConsultation): direct string comparison
        appointments_query = appointments_query.filter(Appointment.time <= end_time_str)
        video_consultations_query = video_consultations_query.filter(VideoConsultation.time <= end_time_str)
        
        # For DateTime fields (Order, Prescription): use strftime to extract HH:MM string for comparison
        orders_query = orders_query.filter(db.func.strftime('%H:%M', Order.order_date) <= end_time_str)
        prescriptions_query = prescriptions_query.filter(db.func.strftime('%H:%M', Prescription.upload_date) <= end_time_str)

    # Execute queries with sorting
    appointments = appointments_query.order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    video_consultations = video_consultations_query.order_by(VideoConsultation.date.desc(), VideoConsultation.time.desc()).all()
    orders = orders_query.order_by(Order.order_date.desc()).all()
    prescriptions = prescriptions_query.order_by(Prescription.upload_date.desc()).all()

    # Calculate total users
    total_users = User.query.count()

    # Total doctors is set to 5 as per your request
    total_doctors = 4

    return render_template(
        "management_dashboard.html",
        total_users=total_users,
        total_doctors=total_doctors,
        appointments=appointments,
        video_consultations=video_consultations,
        orders=orders,
        prescriptions=prescriptions,
        start_date=start_date_str, # Pass filter values back to template
        end_date=end_date_str,
        start_time=start_time_str,
        end_time=end_time_str,
        datetime=datetime # Pass datetime for footer
    )

# --- NEW: Add Manager Route ---
@app.route("/management_add_manager", methods=["GET", "POST"])
def management_add_manager():
    if not session.get("manager_logged_in"):
        flash("Unauthorized access. Please log in as a manager.", "danger")
        return redirect(url_for("management_login"))

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if not (username and email and password and confirm_password):
            flash("All fields are required.", "danger")
            return redirect(url_for("management_add_manager"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("management_add_manager"))

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            flash("Username or Email already exists. Please choose a different one.", "danger")
            return redirect(url_for("management_add_manager"))

        new_manager = User(username=username, email=email, role='manager')
        new_manager.set_password_hash(password)
        
        try:
            db.session.add(new_manager)
            db.session.commit()
            flash(f"New manager '{username}' created successfully!", "success")
            return redirect(url_for("management_users")) # Redirect to users list
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating manager: {str(e)}", "danger")
            return redirect(url_for("management_add_manager"))

    return render_template("management_add_manager.html", datetime=datetime)

@app.route("/management-logout")
def management_logout():
    session.pop("manager_logged_in", None)
    flash("You have been logged out from the management portal.", "info")
    return redirect(url_for("management_login"))

# NEW: Routes for Prescription Management (already existed, kept for completeness)
@app.route("/approve-prescription/<int:prescription_id>", methods=["POST"])
def approve_prescription(prescription_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    prescription = Prescription.query.get_or_404(prescription_id)
    prescription.status = "Approved"
    prescription.notes = "Your prescription has been approved by our pharmacist. You can now proceed to order medicines."
    db.session.commit()

    # Send a notification to the user
    send_user_message(prescription.user_id, f"Your prescription (ID: {prescription.id}) has been approved! You can now order the prescribed medicines.")
    
    flash(f"Prescription ID {prescription.id} for {prescription.user.username} approved and user notified.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/reject-prescription/<int:prescription_id>", methods=["POST"])
def reject_prescription(prescription_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    prescription = Prescription.query.get_or_404(prescription_id)
    rejection_reason = request.form.get("rejection_reason", "No specific reason provided.")
    
    prescription.status = "Rejected"
    prescription.notes = f"Your prescription has been rejected. Reason: {rejection_reason} Please re-upload a clear prescription or contact support."
    db.session.commit()

    # Send a notification to the user
    send_user_message(prescription.user_id, f"Your prescription (ID: {prescription.id}) has been rejected. Reason: {rejection_reason}")

    flash(f"Prescription ID {prescription.id} for {prescription.user.username} rejected and user notified. Reason: {rejection_reason}", "info")
    return redirect(url_for("management_dashboard"))

@app.route("/under-review-prescription/<int:prescription_id>", methods=["POST"])
def under_review_prescription(prescription_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    prescription = Prescription.query.get_or_404(prescription_id)
    review_notes = request.form.get("review_notes", "Under review by pharmacist.")

    prescription.status = "Under Review"
    prescription.notes = f"Your prescription is currently under review. {review_notes}"
    db.session.commit()

    # Send a notification to the user
    send_user_message(prescription.user_id, f"Your prescription (ID: {prescription.id}) is now under review. Please await further updates.")

    flash(f"Prescription ID {prescription.id} for {prescription.user.username} marked as 'Under Review' and user notified.", "info")
    return redirect(url_for("management_dashboard"))

# NEW: Routes for Appointment Management
@app.route("/approve-appointment/<int:appointment_id>", methods=["POST"])
def approve_appointment(appointment_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    appointment = Appointment.query.get_or_404(appointment_id)
    appointment.status = "Approved"
    db.session.commit()

    send_user_message(appointment.user_id, f"Your appointment (ID: {appointment.id}) with {appointment.doctor} on {appointment.date} at {appointment.time} has been approved!")
    flash(f"Appointment ID {appointment.id} for {appointment.user.username} approved.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/reject-appointment/<int:appointment_id>", methods=["POST"])
def reject_appointment(appointment_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    appointment = Appointment.query.get_or_404(appointment_id)
    rejection_reason = request.form.get("rejection_reason", "No specific reason provided.")
    appointment.status = "Rejected"
    db.session.commit()

    send_user_message(appointment.user_id, f"Your appointment (ID: {appointment.id}) with {appointment.doctor} on {appointment.date} at {appointment.time} has been rejected. Reason: {rejection_reason}")
    flash(f"Appointment ID {appointment.id} for {appointment.user.username} rejected. Reason: {rejection_reason}", "info")
    return redirect(url_for("management_dashboard"))

# NEW: Routes for Video Consultation Management
@app.route("/approve-consultation/<int:consultation_id>", methods=["POST"])
def approve_consultation(consultation_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    consultation = VideoConsultation.query.get_or_404(consultation_id)
    consultation.status = "Approved"
    db.session.commit()

    send_user_message(consultation.user_id, f"Your video consultation (ID: {consultation.id}) with {consultation.doctor} on {consultation.date} at {consultation.time} has been approved! Join link: {consultation.meeting_link}")
    flash(f"Video consultation ID {consultation.id} for {consultation.user.username} approved.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/reject-consultation/<int:consultation_id>", methods=["POST"])
def reject_consultation(consultation_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    consultation = VideoConsultation.query.get_or_404(consultation_id)
    rejection_reason = request.form.get("rejection_reason", "No specific reason provided.")
    consultation.status = "Rejected"
    db.session.commit()

    send_user_message(consultation.user_id, f"Your video consultation (ID: {consultation.id}) with {consultation.doctor} on {consultation.date} at {consultation.time} has been rejected. Reason: {rejection_reason}")
    flash(f"Video consultation ID {consultation.id} for {consultation.user.username} rejected. Reason: {rejection_reason}", "info")
    return redirect(url_for("management_dashboard"))

# NEW: Routes for Order Management
@app.route("/process-order/<int:order_id>", methods=["POST"])
def process_order(order_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    order = Order.query.get_or_404(order_id)
    order.status = "Processing" # Change status to processing
    db.session.commit()

    send_user_message(order.user_id, f"Your order (ID: {order.id}) is now being processed!")
    flash(f"Order ID {order.id} for {order.user.username} marked as 'Processing'.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/ship-order/<int:order_id>", methods=["POST"])
def ship_order(order_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    order = Order.query.get_or_404(order_id)
    order.status = "Shipped" # Change status to Shipped
    db.session.commit()

    send_user_message(order.user_id, f"Good news! Your order (ID: {order.id}) has been shipped to {order.delivery_address}!")
    flash(f"Order ID {order.id} for {order.user.username} marked as 'Shipped'.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/complete-order/<int:order_id>", methods=["POST"])
def complete_order(order_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    order = Order.query.get_or_404(order_id)
    order.status = "Delivered" # Change status to Delivered/Completed
    db.session.commit()

    send_user_message(order.user_id, f"Your order (ID: {order.id}) has been successfully delivered!")
    flash(f"Order ID {order.id} for {order.user.username} marked as 'Delivered'.", "success")
    return redirect(url_for("management_dashboard"))

@app.route("/cancel-order/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    if not session.get("manager_logged_in"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("management_login"))

    order = Order.query.get_or_404(order_id)
    rejection_reason = request.form.get("rejection_reason", "No specific reason provided.")
    order.status = "Cancelled"
    db.session.commit()

    # Restore stock for the items in the cancelled order (important for inventory)
    for item in order.order_items:
        medicine = Medicine.query.get(item.medicine_id)
        if medicine:
            medicine.stock += item.quantity
    db.session.commit()

    send_user_message(order.user_id, f"Your order (ID: {order.id}) has been cancelled. Reason: {rejection_reason}. Please contact support for more details.")
    flash(f"Order ID {order.id} for {order.user.username} cancelled. Reason: {rejection_reason}", "info")
    return redirect(url_for("management_dashboard"))


@app.route("/Mangement_aboutus")
def Mangement_aboutus():
    if "user" in session:
        return render_template("Mangement_aboutus.html", username=session["user"], email=session["email"], profile_pic=session["profile_pic"],datetime=datetime)
    return redirect(url_for("login"))
@app.route("/management-profile")
def management_profile():
    if not session.get("manager_logged_in"):
        flash("Please log in as a manager to access this page.", "warning")
        return redirect(url_for("management_login"))

    # You would typically fetch manager-specific data here
    # For now, using placeholders or data from session if available
    manager_username = MANAGEMENT_USERNAME # Using the hardcoded username
    manager_email = "pranikov@uphillhealth.com" # Example email
    manager_role = "Administrator" # Example role
    manager_last_login = session.get("manager_last_login", "Not recorded") # Example: store last login in session
    manager_total_logins = session.get("manager_total_logins", "N/A") # Example: store total logins in session


    return render_template(
        "management_profile.html",
        manager_username=manager_username,
        manager_email=manager_email,
        manager_role=manager_role,
        manager_last_login=manager_last_login,
        manager_total_logins=manager_total_logins,
        datetime=datetime # Pass datetime for the footer
    )
@app.route("/management_users")
def management_users():
    """
    Manager dashboard page for viewing and managing users.
    """
    if not session.get("manager_logged_in"):
        flash("Unauthorized access. Please log in as a manager.", "danger")
        return redirect(url_for("management_login"))

    users = User.query.all()
    return render_template("management_users.html", users=users, datetime=datetime)

if __name__ == "__main__":
    with app.app_context():
        create_database() # Ensure all tables are created and populated
    app.run(host="0.0.0.0", port=5000, debug=True)