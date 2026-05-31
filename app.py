import os
from flask import Flask, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, Doctor, Patient, Visit
from utils import predict_image, generate_pdf_report
from utils import make_shap
from models import db, Doctor, Patient, Visit, AdminHistory
from models import Review
from models import Message
from flask_login import login_required
app = Flask(__name__)
app.secret_key = "super_secret_key_medical"
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
basedir = os.path.abspath(os.path.dirname(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = \
    'sqlite:///' + os.path.join(basedir, 'database.db')


app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

db.init_app(app)


def add_history(action, details):

    history = AdminHistory(
        action=action,
        details=details
    )

    db.session.add(history)

    db.session.commit()



from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView


admin = Admin(app, name='Admin Panel')
admin.add_view(ModelView(Doctor, db.session))
admin.add_view(ModelView(Patient, db.session))
admin.add_view(ModelView(Visit, db.session))



with app.app_context():
    db.create_all()

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# =====================
# AUTH ROUTES
# =====================
@app.route("/", methods=["GET", "POST"])
def login():
    if "doctor_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        doctor = Doctor.query.filter_by(username=username).first()
        if doctor and check_password_hash(doctor.password, password):
            session["doctor_id"] = doctor.id
            session["doctor_name"] = doctor.name
            add_history(
               "Doctor Login",
               f"{doctor.name} logged in"
            )      
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials, please try again.", "danger")
            
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "doctor_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        name = request.form.get("name")
        username = request.form.get("username")
        password = request.form.get("password")
        
        existing_doctor = Doctor.query.filter_by(username=username).first()
        if existing_doctor:
            flash("Username already exists.", "warning")
        else:
            hashed_pw = generate_password_hash(password)
            new_doctor = Doctor(name=name, username=username, password=hashed_pw)
            db.session.add(new_doctor)
            db.session.commit()
            add_history(
                "New Doctor",
                f"Doctor {name} registered successfully"
            )
            flash("Account created successfully! Please login.", "success")
            return redirect(url_for("login"))
            
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


translations = {

    "en": {
        "dashboard": "Doctor Dashboard",
        "add_patient": "Add New Patient"
    },

    "fr": {
        "dashboard": "Tableau de bord",
        "add_patient": "Ajouter un patient"
    },

    "ar": {
        "dashboard": "لوحة التحكم",
        "add_patient": "إضافة مريض"
    }

}


# =====================
# DASHBOARD ROUTES
# =====================
@app.route('/dashboard')
def dashboard():

    lang = session.get('lang', 'en')

    translations = {

        "en": {
            "dashboard": "Doctor Dashboard",
            "add_patient": "Add New Patient"
        },

        "fr": {
            "dashboard": "Tableau de bord",
            "add_patient": "Ajouter un patient"
        },

        "ar": {
            "dashboard": "لوحة التحكم",
            "add_patient": "إضافة مريض"
        }

    }

    texts = translations[lang]

    patients = Patient.query.all()

    return render_template(
        'dashboard.html',
        patients=patients,
        texts=texts
    )
@app.route("/add_patient", methods=["POST"])
def add_patient():
    if "doctor_id" not in session:
        return redirect(url_for("login"))
        
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    age = request.form.get("age")
    gender = request.form.get("gender")
    doctor_id = session["doctor_id"]
    
    new_patient = Patient(first_name=first_name, last_name=last_name, age=age, gender=gender, doctor_id=doctor_id)
    db.session.add(new_patient)
    db.session.commit()
    
    flash("Patient added successfully.", "success")
    return redirect(url_for("dashboard"))

@app.route("/patient/<int:patient_id>")
def patient_view(patient_id):
    if "doctor_id" not in session:
        return redirect(url_for("login"))
        
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != session["doctor_id"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))
        
    visits = Visit.query.filter_by(patient_id=patient.id).order_by(Visit.date.desc()).all()
    
    return render_template("patient.html", patient=patient, visits=visits)

# =====================
# PREDICTION ROUTES
# =====================
@app.route("/predict/<int:patient_id>", methods=["POST"])
def predict(patient_id):
    if "doctor_id" not in session:
        return redirect(url_for("login"))
        
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != session["doctor_id"]:
        return redirect(url_for("dashboard"))
        
    if "image" not in request.files:
        flash("No file uploaded", "danger")
        return redirect(url_for("patient_view", patient_id=patient_id))
        
    file = request.files["image"]
    if file.filename == "":
        flash("No selected file", "danger")
        return redirect(url_for("patient_view", patient_id=patient_id))
        
    if file:
        filename = secure_filename(file.filename)
        # Add timestamp to avoid overwriting
        import time
        filename = f"{int(time.time())}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # ML Inference
        label, conf, gradcam, shap_img = predict_image(filepath)
        
        # Save Visit
        rel_filepath = f"uploads/{filename}"
        new_visit = Visit(
            patient_id=patient.id,
            image_path=rel_filepath,
            prediction=label,
            confidence=conf,
            gradcam_path=gradcam,
            shap_path=shap_img
        )
        db.session.add(new_visit)
        db.session.commit()
        add_history(
            "MRI Uploaded",
            f"MRI uploaded for patient {patient.first_name}"
        )
        return redirect(url_for("result", visit_id=new_visit.id))

@app.route("/result/<int:visit_id>")
def result(visit_id):
    if "doctor_id" not in session:
        return redirect(url_for("login"))
        
    visit = Visit.query.get_or_404(visit_id)
    patient = Patient.query.get(visit.patient_id)
    
    if patient.doctor_id != session["doctor_id"]:
        return redirect(url_for("dashboard"))
        
    return render_template("result.html", visit=visit, patient=patient)

@app.route("/report/<int:visit_id>")
def generate_report(visit_id):
    if "doctor_id" not in session:
        return redirect(url_for("login"))
        
    visit = Visit.query.get_or_404(visit_id)
    patient = Patient.query.get(visit.patient_id)
    doctor = Doctor.query.get(session["doctor_id"])
    
    if patient.doctor_id != session["doctor_id"]:
        return redirect(url_for("dashboard"))
        
    pdf_path = generate_pdf_report(patient, doctor, visit)
    
    return redirect(url_for("static", filename=pdf_path))

from utils import make_gradcam



admins = [
    {
        "username": "khadidja",
        "password": "admin123"
    },

    {
        "username": "hanane",
        "password": "123456"
    }
]

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        for admin in admins:

            if username == admin["username"] and password == admin["password"]:

                session["admin"] = username

                add_history(
                    "Admin Login",
                    f"{username} logged into dashboard"
                )

                return redirect("/admin/dashboard")

        flash("Wrong admin credentials")

    return render_template("admin_login.html")






@app.route("/generate_gradcam/<int:visit_id>")
def generate_gradcam(visit_id):
    visit = Visit.query.get_or_404(visit_id)

    img_path = os.path.join("static", visit.image_path)

    gradcam_path = make_gradcam(img_path)

    visit.gradcam_path = gradcam_path
    db.session.commit()
    add_history(
        "GradCAM Generated",
        f"GradCAM generated for visit {visit.id}"
    )
    return redirect(url_for("result", visit_id=visit.id))



@app.route("/generate_shap/<int:visit_id>")
def generate_shap(visit_id):

    if "doctor_id" not in session:
        return redirect(url_for("login"))

    visit = Visit.query.get_or_404(visit_id)

    patient = Patient.query.get(visit.patient_id)

    if patient.doctor_id != session["doctor_id"]:
        return redirect(url_for("dashboard"))

    from utils import make_shap, feature_extractor

    img_path = os.path.join("static", visit.image_path)

    shap_path = make_shap(
        img_path,
        feature_extractor
    )

    visit.shap_path = shap_path

    db.session.commit()

    flash("SHAP generated successfully!", "success")
    add_history(
        "SHAP Generated",
        f"SHAP explanation generated for patient {patient.first_name}"
    )
    return redirect(url_for("result", visit_id=visit.id))


@app.route("/admin/dashboard")
def admin_dashboard():

    doctors_count = Doctor.query.count()
    patients_count = Patient.query.count()
    visits_count = Visit.query.count()

    doctors = Doctor.query.all()

    history = AdminHistory.query.order_by(
        AdminHistory.date.desc()
    ).all()

    return render_template(
        "admin_dashboard.html",
        doctors_count=doctors_count,
        patients_count=patients_count,
        visits_count=visits_count,
        doctors=doctors,
        history=history
    )

@app.route("/admin/doctors")
def admin_doctors():

    doctors = Doctor.query.all()

    return render_template(
        "admin_doctors.html",
        doctors=doctors
    )


@app.route("/delete_doctor/<int:id>")
def delete_doctor(id):

    doctor = Doctor.query.get_or_404(id)
    add_history(
        "Doctor Deleted",
        f"Doctor {doctor.name} deleted"
    )
    # حذف المرضى تاعو
    patients = Patient.query.filter_by(doctor_id=id).all()

    for patient in patients:

        Visit.query.filter_by(patient_id=patient.id).delete()

        db.session.delete(patient)

    db.session.delete(doctor)

    db.session.commit()

    return redirect("/admin/doctors")

@app.route("/edit_doctor/<int:id>", methods=["GET", "POST"])
def edit_doctor(id):

    doctor = Doctor.query.get_or_404(id)

    if request.method == "POST":

        doctor.name = request.form.get("name")
        doctor.username = request.form.get("username")

        db.session.commit()

        return redirect("/admin/doctors")

    return render_template(
        "edit_doctor.html",
        doctor=doctor
    )
@app.route("/admin/analytics")
def admin_analytics():
    return render_template("admin_analytics.html")


@app.route("/admin/settings")
def admin_settings():
    return render_template("admin_settings.html")

# =========================
# ADMIN EXTRA PAGES
# =========================

@app.route("/admin/profile")
def admin_profile():

    return render_template("admin_profile.html")


@app.route("/admin/messages")
def admin_messages():

    messages = Message.query.order_by(
        Message.date.desc()
    ).all()

    return render_template(
        "admin_messages.html",
        messages=messages
    )

@app.route("/admin/history")
def admin_history():

    history = AdminHistory.query.order_by(
        AdminHistory.date.desc()
    ).all()

    return render_template(
        "admin_history.html",
        history=history
    )


@app.route("/delete_patient/<int:patient_id>")
def delete_patient(patient_id):

    patient = Patient.query.get_or_404(patient_id)

    db.session.delete(patient)

    db.session.commit()

    flash("Patient deleted successfully")

    return redirect(url_for("dashboard"))

@app.route("/add_review", methods=["POST"])
def add_review():

    if "doctor_id" not in session:
        return redirect(url_for("login"))

    doctor = Doctor.query.get(session["doctor_id"])

    rating = request.form.get("rating")
    message = request.form.get("message")

    review = Review(
        doctor_name=doctor.name,
        rating=rating,
        message=message
    )

    db.session.add(review)
    db.session.commit()

    add_history(
        "New Review",
        f"{doctor.name} added feedback"
    )

    flash("Review added successfully!")

    return redirect(url_for("dashboard"))

@app.route("/send_message", methods=["POST"])
def send_message():

    print("SEND MESSAGE ROUTE WORKING")

    if "doctor_id" not in session:
        return redirect(url_for("login"))

    doctor = Doctor.query.get(session["doctor_id"])

    subject = request.form.get("subject")
    content = request.form.get("content")

    print(subject)
    print(content)

    new_message = Message(
        doctor_name=doctor.name,
        subject=subject,
        content=content
    )

    db.session.add(new_message)
    db.session.commit()

    print("MESSAGE SAVED")

    flash("Message sent successfully!")

    return redirect(url_for("dashboard"))


@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
def edit_patient(patient_id):

    patient = Patient.query.get_or_404(patient_id)

    if request.method == 'POST':

        patient.first_name = request.form['first_name']
        patient.last_name = request.form['last_name']
        patient.age = request.form['age']
        patient.gender = request.form['gender']

        db.session.commit()

        return redirect(url_for('dashboard'))

    return render_template(
        'edit_patient.html',
        patient=patient
    )

#if __name__ == "__main__":
    #app.run(debug=True, port=5000)
    #app.run(host="0.0.0.0", port=5000, debug=True)
    #app.run(host="0.0.0.0", port=5000, debug=False)
    #app.run(host="0.0.0.0", port=5000, use_reloader=False)

#if __name__ == "__main__":
    #app.run(
        #host="0.0.0.0",
        #port=5000,
       # debug=False,
      #  use_reloader=False,
     #   threaded=True
    #)
    #app.run(host="0.0.0.0", port=5000, debug=True)

if __name__ == "__main__":
    app.run(debug=False)