import os
import secrets
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import markdown


from listen import transcribe_audio
from summarizator import process_lecture

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Настройка базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    lectures = db.relationship('Lecture', backref='user', lazy=True)

class Lecture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.String(100), nullable=False)  # Формат: YYYYMMDDHHMMSS
    summary = db.Column(db.Text, nullable=False)
    # Сохраняем файлы в БД в виде бинарных данных
    docx_data = db.Column(db.LargeBinary)  # Содержимое DOCX
    pdf_data = db.Column(db.LargeBinary)   # Содержимое PDF
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def create_database():
    if not os.path.exists("app.db"):
        with app.app_context():
            db.create_all()
        print("Database created!")
    else:
        print("Database already exists.")

# Папка для временного хранения аудио
UPLOAD_FOLDER = "D://lemon/summarize_lecture/audio_temp"
# Папка, куда генерируются файлы DOCX и PDF
SAVED_LECTURE_FOLDER = "D://lemon/summarize_lecture/saved_lecture"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SAVED_LECTURE_FOLDER"] = SAVED_LECTURE_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAVED_LECTURE_FOLDER, exist_ok=True)

def clear_upload_folder():
    """Очищает временную папку загрузки аудиофайлов."""
    if os.path.exists(UPLOAD_FOLDER):
        for file in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Ошибка при очистке папки загрузки: {e}")


def get_generated_files():
    # Пути к файлам
    docx_filename = "summarized_lecture_docx.docx"
    pdf_filename = "summarized_lecture_pdf.pdf"
    docx_path = os.path.join(app.config["SAVED_LECTURE_FOLDER"], docx_filename)
    pdf_path = os.path.join(app.config["SAVED_LECTURE_FOLDER"], pdf_filename)
    # Считываем файлы в бинарном виде
    with open(docx_path, "rb") as f:
        docx_data = f.read()
    with open(pdf_path, "rb") as f:
        pdf_data = f.read()
    return docx_data, pdf_data


@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/home", methods=["GET", "POST"])
@login_required
def index():
    """
    Пользователь загружает аудиофайл.
    После обработки:
      - DOCX и PDF генерируются внешней системой и сохраняются в SAVED_LECTURE_FOLDER,
      - мы считываем их и сохраняем их содержимое (байты) в БД.
    """
    if request.method == "POST":
        clear_upload_folder()
        audio_file = request.files.get("audio_file")
        if audio_file:
            filename = secure_filename(audio_file.filename)
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            audio_file.save(file_path)

            language = request.form["language"]
            detail_level = int(request.form["detail_level"])
            smart_additions = (request.form.get("smart_additions") == "True")

            # Транскрибирование аудио -> text
            transcribed_text = transcribe_audio(file_path, language)
            # Суммаризация
            processed_text = process_lecture(transcribed_text, detail_level, smart_additions)

            docx_data, pdf_data = get_generated_files()

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            lecture = Lecture(
                timestamp=timestamp,
                summary=processed_text,
                docx_data=docx_data,
                pdf_data=pdf_data,
                user_id=current_user.id
            )
            db.session.add(lecture)
            db.session.commit()

            return redirect(url_for("result", lecture_id=lecture.id))
    return render_template("index.html")

@app.route("/result")
@login_required
def result():
    lecture_id = request.args.get("lecture_id")
    lecture = Lecture.query.filter_by(id=lecture_id, user_id=current_user.id).first()
    if not lecture:
        flash("Лекция не найдена", "danger")
        return redirect(url_for("index"))

    # Преобразуем Markdown в HTML
    html_text = markdown.markdown(lecture.summary)

    docx_exists = bool(lecture.docx_data)
    pdf_exists = bool(lecture.pdf_data)

    return render_template(
        "result.html",
        lecture_id=lecture.id,
        text=html_text,
        docx_exists=docx_exists,
        pdf_exists=pdf_exists
    )

@app.route("/download_docx/<int:lecture_id>")
@login_required
def download_docx(lecture_id):
    lecture = Lecture.query.filter_by(id=lecture_id, user_id=current_user.id).first()
    if not lecture or not lecture.docx_data:
        flash("DOCX не найден для данной лекции", "warning")
        return redirect(url_for("dashboard"))

    return send_file(
        BytesIO(lecture.docx_data),
        as_attachment=True,
        download_name="lecture.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@app.route("/download_pdf/<int:lecture_id>")
@login_required
def download_pdf(lecture_id):
    lecture = Lecture.query.filter_by(id=lecture_id, user_id=current_user.id).first()
    if not lecture or not lecture.pdf_data:
        flash("PDF не найден для данной лекции", "warning")
        return redirect(url_for("dashboard"))

    return send_file(
        BytesIO(lecture.pdf_data),
        as_attachment=True,
        download_name="lecture.pdf",
        mimetype="application/pdf"
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        remember_me = bool(request.form.get("remember"))

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember_me)
            flash("Вы успешно вошли в систему!", "success")
            return redirect(url_for("index"))
        else:
            flash("Неверное имя пользователя или пароль", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Пользователь с таким именем уже существует", "warning")
        else:
            hashed_password = generate_password_hash(password)
            new_user = User(username=username, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            flash("Регистрация прошла успешно, теперь вы можете войти", "success")
            return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из системы", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    search_query = request.args.get("search", "", type=str).strip()
    date_from_str = request.args.get("date_from", "")
    date_to_str = request.args.get("date_to", "")

    # Базовый запрос: все лекции текущего пользователя
    lectures_query = Lecture.query.filter_by(user_id=current_user.id)

    # Фильтр по содержанию (summary) через LIKE
    if search_query:
        lectures_query = lectures_query.filter(Lecture.summary.like(f"%{search_query}%"))

    # Фильтр по дате: преобразуем дату из формы (YYYY-MM-DD) в префикс YYYYMMDD
    def date_to_timestamp_prefix(dstr):
        return dstr.replace('-', '')

    if date_from_str:
        from_prefix = date_to_timestamp_prefix(date_from_str)
        lectures_query = lectures_query.filter(Lecture.timestamp >= from_prefix)
    if date_to_str:
        to_prefix = date_to_timestamp_prefix(date_to_str)
        lectures_query = lectures_query.filter(Lecture.timestamp <= to_prefix)

    # Получаем лекции, отсортированные по timestamp в порядке убывания
    lectures = lectures_query.order_by(Lecture.timestamp.desc()).all()

    # Для каждой лекции преобразуем timestamp и Markdown-текст
    formatted_lectures = []
    for lecture in lectures:
        try:
            dt = datetime.strptime(lecture.timestamp, "%Y%m%d%H%M%S")
            formatted_timestamp = dt.strftime("%d-%m-%Y %H:%M:%S")
        except Exception:
            formatted_timestamp = lecture.timestamp

        # Преобразуем Markdown в HTML
        html_summary = markdown.markdown(lecture.summary)

        # Добавляем новые атрибуты к объекту lecture
        lecture.formatted_timestamp = formatted_timestamp
        lecture.html_summary = html_summary
        formatted_lectures.append(lecture)

    return render_template("dashboard.html", lectures=formatted_lectures)

if __name__ == "__main__":
    create_database()
    app.run(debug=True)
