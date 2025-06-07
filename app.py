from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import openai
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

### MODELS ###
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    suggestions = db.Column(db.Text, nullable=True)  # Store response suggestions

class MoodEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mood_score = db.Column(db.Integer, nullable=False)  # 1-4 scale
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)

class SelfCarePlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

### ROUTES ###
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Clear any existing flash messages on login page
    if request.method == 'GET':
        session.pop('_flashes', None)
    
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        user = User.query.filter(db.func.lower(User.username) == username).first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('chat'))
        else:
            flash('Invalid username or password.')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        if User.query.filter(db.func.lower(User.username) == username).first():
            flash('Username already exists.')
        else:
            new_user = User(username=username, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash('Signup successful. Please log in.')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    import random
    import logging
    
    # Add logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Daily affirmations/tips
    daily_tips = [
        "🌞 You are doing better than you think. One breath at a time.",
        # ... rest of your tips
    ]
    
    daily_tip = random.choice(daily_tips)
    history = ChatHistory.query.filter_by(user_id=current_user.id).all()
    show_self_care_offer = len(history) >= 3
    
    if request.method == 'POST':
        logger.info("POST request received")
        
        # Handle chat message
        if 'message' in request.form:
            user_message = request.form['message']
            logger.info(f"User message: {user_message}")
            
            # Check if OpenAI API key exists
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.error("No OpenAI API key found!")
                assistant_reply = "Configuration error: Missing API key"
                suggestions = "Contact support|Try again later|Check settings"
            else:
                logger.info("OpenAI API key found, making request...")
                
                try:
                    # Your existing OpenAI code here
                    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7
                    )
                    full_response = response['choices'][0]['message']['content'].strip()
                    logger.info("OpenAI response received successfully")
                    
                    # Your existing response processing code...
                    
                except Exception as e:
                    logger.error(f"OpenAI API Error: {str(e)}")
                    assistant_reply = f"API Error: {str(e)}"
                    suggestions = "Try again|Contact support|Check connection"
            
            # Save to DB (your existing code)
            chat_entry = ChatHistory(
                user_id=current_user.id, 
                message=user_message, 
                response=assistant_reply.strip(),
                suggestions=suggestions
            )
            db.session.add(chat_entry)
            db.session.commit()
            history.append(chat_entry)
    
    return render_template("index_auth.html", 
                         chat_history=history, 
                         greeting="Hello! How are you feeling today?",
                         daily_tip=daily_tip,
                         show_self_care_offer=show_self_care_offer)

@app.route('/view_plan/<int:plan_id>')
@login_required
def view_plan(plan_id):
    plan = SelfCarePlan.query.filter_by(id=plan_id, user_id=current_user.id).first_or_404()
    return render_template("self_care_plan.html", plan=plan)

@app.route('/mood_history')
@login_required
def mood_history():
    moods = MoodEntry.query.filter_by(user_id=current_user.id).order_by(MoodEntry.timestamp.desc()).limit(30).all()
    return render_template("mood_history.html", moods=moods)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Get port from environment variable (Render provides this)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)