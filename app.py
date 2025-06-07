from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from openai import OpenAI
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import random

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your_fallback_secret_key_here')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Add logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    # Daily affirmations/tips
    daily_tips = [
        "🌞 You are doing better than you think. One breath at a time.",
        "🌱 Progress, not perfection. Every small step counts.",
        "💙 Be kind to yourself today. You deserve compassion.",
        "🌈 This feeling is temporary. You have overcome challenges before.",
        "⭐ Your mental health matters. Take time for yourself today.",
        "🌸 Breathe deeply. You are exactly where you need to be.",
        "🦋 Growth happens in moments of discomfort. You're growing.",
        "💪 You are stronger than you realize. Trust in your resilience.",
        "🌺 Take a moment to appreciate how far you've come.",
        "✨ Your feelings are valid. It's okay to not be okay sometimes."
    ]
    
    # Get random daily tip
    daily_tip = random.choice(daily_tips)
    
    history = ChatHistory.query.filter_by(user_id=current_user.id).all()
    show_self_care_offer = len(history) >= 3
    
    if request.method == 'POST':
        logger.info("POST request received")
        
        # Handle mood tracking
        if 'mood_score' in request.form:
            mood_score = int(request.form['mood_score'])
            mood_notes = request.form.get('mood_notes', '')
            mood_entry = MoodEntry(user_id=current_user.id, mood_score=mood_score, notes=mood_notes)
            db.session.add(mood_entry)
            db.session.commit()
            # Don't flash message, just redirect quietly
            return redirect(url_for('chat'))
        
        # Handle self-care plan generation
        if 'generate_plan' in request.form:
            # Analyze recent conversations for personalized plan
            recent_messages = [chat.message for chat in history[-5:]]  # Last 5 messages
            conversation_context = " ".join(recent_messages)
            
            plan_prompt = f"""Based on this user's recent conversations: "{conversation_context}"
            
            Create a simple, personalized 3-step self-care plan for today. Make it specific, actionable, and supportive.
            
            Format as:
            **Step 1:** [specific action]
            **Step 2:** [specific action] 
            **Step 3:** [specific action]
            
            Keep it encouraging and focus on immediate, doable activities."""
            
            try:
                plan_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": plan_prompt}],
                    temperature=0.7
                )
                plan_content = plan_response.choices[0].message.content.strip()
                
                # Save plan to database
                self_care_plan = SelfCarePlan(user_id=current_user.id, plan_content=plan_content)
                db.session.add(self_care_plan)
                db.session.commit()
                
                flash('Your personalized self-care plan has been generated! 🌟')
                return redirect(url_for('view_plan', plan_id=self_care_plan.id))
            except Exception as e:
                logger.error(f"Self-care plan API Error: {str(e)}")
                flash('Sorry, there was an error generating your plan. Please try again.')
        
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
                
                # Enhanced system prompt with better suggestions
                system_prompt = """You are a compassionate mental health assistant. Provide helpful, supportive responses about mental health, meditation, breathing exercises, and wellness.

                IMPORTANT: Always end your response with exactly 3 short suggestions separated by | (pipe character).
                
                Choose suggestions from these helpful options:
                - Try a 5-minute meditation
                - Practice box breathing
                - Learn grounding techniques  
                - Try progressive muscle relaxation
                - Practice mindful walking
                - Do a body scan meditation
                - Try loving-kindness meditation
                - Practice the 4-7-8 breathing
                - Learn the 5-4-3-2-1 technique
                - Try guided imagery
                - Practice gratitude meditation
                - Do gentle stretching
                - Try journaling prompts
                - Practice deep breathing
                - Learn stress relief techniques
                
                Format your response exactly like this:
                [Your helpful response here]
                
                ---SUGGESTIONS---
                Try a 5-minute meditation|Practice box breathing|Learn grounding techniques
                
                Keep suggestions short and actionable. Focus on practical techniques users can do immediately."""
                
                try:
                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7
                    )
                    full_response = response.choices[0].message.content.strip()
                    logger.info("OpenAI response received successfully")
                    
                    # Split response and suggestions more carefully
                    if "---SUGGESTIONS---" in full_response:
                        parts = full_response.split("---SUGGESTIONS---")
                        assistant_reply = parts[0].strip()
                        suggestions_text = parts[1].strip()
                        
                        # Clean up suggestions and ensure proper separation
                        suggestions = suggestions_text.replace('\n', '|').replace('  ', ' ')
                        # Remove any numbering or bullet points
                        suggestions = suggestions.replace('1.', '').replace('2.', '').replace('3.', '')
                        suggestions = suggestions.replace('-', '').replace('•', '').replace('*', '')
                        
                        # If suggestions don't contain pipes, try to split by common separators
                        if '|' not in suggestions:
                            # Try splitting by periods, commas, or line breaks
                            if '.' in suggestions:
                                suggestion_parts = [s.strip() for s in suggestions.split('.') if s.strip()]
                                suggestions = '|'.join(suggestion_parts[:3])
                            elif ',' in suggestions:
                                suggestion_parts = [s.strip() for s in suggestions.split(',') if s.strip()]
                                suggestions = '|'.join(suggestion_parts[:3])
                            else:
                                # Fallback if parsing fails
                                suggestions = "Try a 5-minute meditation|Practice deep breathing|Learn stress relief techniques"
                        
                    else:
                        assistant_reply = full_response
                        suggestions = "Try a 5-minute meditation|Practice box breathing|Learn grounding techniques"
                    
                except Exception as e:
                    logger.error(f"OpenAI API Error: {str(e)}")
                    assistant_reply = "Sorry, there was an error generating a response. Please try again."
                    suggestions = "Try again|Practice deep breathing|Try meditation"
            
            # Save to DB
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
    # Create tables if they don't exist
    with app.app_context():
        db.create_all()
    
    # Get port from environment variable (Render provides this)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)