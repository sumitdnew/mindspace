from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import openai
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
import random
import json
from collections import defaultdict, Counter

load_dotenv()


# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

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

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    mood_score = db.Column(db.Integer, nullable=True)  # Optional mood with journal
    tags = db.Column(db.String(500), nullable=True)  # Comma-separated tags
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_private = db.Column(db.Boolean, default=True)

class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(100), nullable=False)  # mental_health, meditation, exercise, etc.
    target_value = db.Column(db.Integer, nullable=True)  # e.g., 7 for "meditate 7 times this week"
    current_value = db.Column(db.Integer, default=0)
    target_date = db.Column(db.Date, nullable=True)
    is_completed = db.Column(db.Boolean, default=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)

class GoalProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goal_id = db.Column(db.Integer, db.ForeignKey('goal.id'), nullable=False)
    progress_value = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    metric_name = db.Column(db.String(100), nullable=False)  # meditation_minutes, mood_entries, journal_entries
    metric_value = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    content_type = db.Column(db.String(50), nullable=False)  # article, video, exercise, audio
    category = db.Column(db.String(100), nullable=False)  # anxiety, depression, stress, meditation, etc.
    url = db.Column(db.String(500), nullable=True)
    content = db.Column(db.Text, nullable=True)  # For exercises or short content
    difficulty_level = db.Column(db.String(20), nullable=False)  # beginner, intermediate, advanced
    duration_minutes = db.Column(db.Integer, nullable=True)
    tags = db.Column(db.String(500), nullable=True)
    is_featured = db.Column(db.Boolean, default=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

### ROUTES ###

@app.route('/test')
def test():
    return "Test route works!"

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

@app.route('/debug_moods')
@login_required
def debug_moods():
    """Debug route to check mood data"""
    moods = MoodEntry.query.filter_by(user_id=current_user.id).all()
    mood_data = []
    for mood in moods:
        mood_data.append({
            'id': mood.id,
            'score': mood.mood_score,
            'notes': mood.notes,
            'timestamp': mood.timestamp.strftime('%Y-%m-%d %H:%M')
        })
    
    return {
        'user_id': current_user.id,
        'mood_count': len(moods),
        'moods': mood_data
    }

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
        
        # Handle mood tracking - IMPROVED VERSION
        if 'mood_score' in request.form:
            try:
                mood_score = int(request.form['mood_score'])
                mood_notes = request.form.get('mood_notes', '').strip()
                
                logger.info(f"Saving mood: score={mood_score}, notes='{mood_notes}', user_id={current_user.id}")
                
                # Validate mood score
                if mood_score not in [1, 2, 3, 4]:
                    raise ValueError(f"Invalid mood score: {mood_score}")
                
                # Create mood entry
                mood_entry = MoodEntry(
                    user_id=current_user.id, 
                    mood_score=mood_score, 
                    notes=mood_notes
                )
                
                # Save to database
                db.session.add(mood_entry)
                db.session.commit()
                
                logger.info(f"Mood saved successfully with ID: {mood_entry.id}")
                
                # Show success message
                mood_emojis = ["😞", "😐", "🙂", "😃"]
                mood_labels = ["Sad", "Okay", "Good", "Great"]
                flash(f'Mood logged! You selected: {mood_emojis[mood_score-1]} {mood_labels[mood_score-1]}')
                
            except ValueError as e:
                logger.error(f"Invalid mood score: {str(e)}")
                flash('Invalid mood selection. Please try again.')
            except Exception as e:
                logger.error(f"Error saving mood: {str(e)}")
                flash('Error saving mood. Please try again.')
            
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
                plan_response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": plan_prompt}],
                    temperature=0.7
                )
                plan_content = plan_response['choices'][0]['message']['content'].strip()
                
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

# NEW JOURNAL ROUTES
@app.route('/journal')
@login_required
def journal():
    """Journal listing page"""
    entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.timestamp.desc()).limit(20).all()
    return render_template('journal.html', entries=entries)

@app.route('/journal/new', methods=['GET', 'POST'])
@login_required
def new_journal_entry():
    """Create new journal entry"""
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        mood_score = request.form.get('mood_score')
        tags = request.form.get('tags', '').strip()
        
        if not title or not content:
            flash('Title and content are required.')
            return render_template('new_journal.html')
        
        # Create journal entry
        entry = JournalEntry(
            user_id=current_user.id,
            title=title,
            content=content,
            mood_score=int(mood_score) if mood_score else None,
            tags=tags
        )
        
        db.session.add(entry)
        
        # Also create a mood entry if mood was provided
        if mood_score:
            mood_entry = MoodEntry(
                user_id=current_user.id,
                mood_score=int(mood_score),
                notes=f"From journal: {title[:50]}"
            )
            db.session.add(mood_entry)
        
        db.session.commit()
        flash('Journal entry saved successfully! 📝')
        return redirect(url_for('journal'))
    
    return render_template('new_journal.html')

@app.route('/journal/<int:entry_id>')
@login_required
def view_journal_entry(entry_id):
    """View specific journal entry"""
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=current_user.id).first_or_404()
    return render_template('view_journal.html', entry=entry)

# NEW GOALS ROUTES
@app.route('/goals')
@login_required
def goals():
    """Goals dashboard"""
    active_goals = Goal.query.filter_by(user_id=current_user.id, is_completed=False).all()
    completed_goals = Goal.query.filter_by(user_id=current_user.id, is_completed=True).limit(10).all()
    
    # Calculate progress for each goal
    for goal in active_goals:
        if goal.target_value:
            goal.progress_percentage = min(100, (goal.current_value / goal.target_value) * 100)
        else:
            goal.progress_percentage = 100 if goal.is_completed else 0
    
    return render_template('goals.html', active_goals=active_goals, completed_goals=completed_goals)

@app.route('/goals/new', methods=['GET', 'POST'])
@login_required
def new_goal():
    """Create new goal"""
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form.get('description', '').strip()
        category = request.form['category']
        target_value = request.form.get('target_value')
        target_date = request.form.get('target_date')
        
        if not title:
            flash('Goal title is required.')
            return render_template('new_goal.html')
        
        goal = Goal(
            user_id=current_user.id,
            title=title,
            description=description,
            category=category,
            target_value=int(target_value) if target_value else None,
            target_date=datetime.strptime(target_date, '%Y-%m-%d').date() if target_date else None
        )
        
        db.session.add(goal)
        db.session.commit()
        flash('Goal created successfully! 🎯')
        return redirect(url_for('goals'))
    
    return render_template('new_goal.html')

@app.route('/goals/<int:goal_id>/progress', methods=['POST'])
@login_required
def update_goal_progress():
    """Update goal progress"""
    goal_id = request.form['goal_id']
    progress_value = int(request.form['progress_value'])
    notes = request.form.get('notes', '').strip()
    
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    
    # Add progress entry
    progress = GoalProgress(
        goal_id=goal.id,
        progress_value=progress_value,
        notes=notes
    )
    
    # Update goal current value
    goal.current_value += progress_value
    
    # Check if goal is completed
    if goal.target_value and goal.current_value >= goal.target_value:
        goal.is_completed = True
        flash(f'🎉 Congratulations! You completed your goal: {goal.title}')
    
    db.session.add(progress)
    db.session.commit()
    
    return redirect(url_for('goals'))

# NEW INSIGHTS ROUTES
@app.route('/insights')
@login_required
def insights():
    """Personal insights and analytics"""
    # Get data for the last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Mood data
    moods = MoodEntry.query.filter(
        MoodEntry.user_id == current_user.id,
        MoodEntry.timestamp >= thirty_days_ago
    ).all()
    
    # Chat activity
    chats = ChatHistory.query.filter(
        ChatHistory.user_id == current_user.id,
        ChatHistory.timestamp >= thirty_days_ago
    ).all()
    
    # Journal entries
    journals = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.timestamp >= thirty_days_ago
    ).all()
    
    # Calculate insights
    insights_data = {
        'total_mood_entries': len(moods),
        'average_mood': round(sum(m.mood_score for m in moods) / len(moods), 1) if moods else 0,
        'best_mood_day': None,
        'most_active_day': None,
        'total_chat_sessions': len(chats),
        'total_journal_entries': len(journals),
        'mood_trend': 'stable',  # Will calculate based on recent vs earlier data
        'insights': []
    }
    
    # Calculate mood trend
    if len(moods) >= 7:
        recent_moods = [m.mood_score for m in moods[:7]]  # Last 7 entries
        earlier_moods = [m.mood_score for m in moods[-7:]]  # Earlier 7 entries
        
        recent_avg = sum(recent_moods) / len(recent_moods)
        earlier_avg = sum(earlier_moods) / len(earlier_moods)
        
        if recent_avg > earlier_avg + 0.3:
            insights_data['mood_trend'] = 'improving'
        elif recent_avg < earlier_avg - 0.3:
            insights_data['mood_trend'] = 'declining'
    
    # Generate personalized insights
    insights_data['insights'] = generate_insights(moods, chats, journals)
    
    return render_template('insights.html', data=insights_data)

def generate_insights(moods, chats, journals):
    """Generate personalized insights based on user data"""
    insights = []
    
    if not moods:
        insights.append("Start tracking your mood daily to get personalized insights! 📊")
        return insights
    
    # Mood patterns
    mood_scores = [m.mood_score for m in moods]
    avg_mood = sum(mood_scores) / len(mood_scores)
    
    if avg_mood >= 3.5:
        insights.append("🌟 Your mood has been consistently positive! Keep up the great work.")
    elif avg_mood >= 2.5:
        insights.append("💪 Your mood is stable. Consider adding more self-care activities to boost it further.")
    else:
        insights.append("💙 Your mood could use some support. Try daily meditation or reach out to a friend.")
    
    # Activity insights
    if len(chats) >= 10:
        insights.append(f"📱 You've been actively using the chat feature ({len(chats)} sessions). Great engagement!")
    
    if len(journals) >= 5:
       insights.append(f"Excellent journaling habit! You've written {len(journals)} entries this month.✍️")
    elif len(journals) >= 1:
        insights.append("📝 You've started journaling! Try to write a few times per week for better insights.")
    else:
        insights.append("📔 Consider starting a journal to track your thoughts and feelings.")
    
    # Timing insights
    if moods:
        mood_hours = [m.timestamp.hour for m in moods]
        most_common_hour = Counter(mood_hours).most_common(1)[0][0]
        
        if most_common_hour < 12:
            insights.append("🌅 You tend to check in with your mood in the morning. Great way to start the day!")
        elif most_common_hour > 18:
            insights.append("🌙 You often reflect on your mood in the evening. Consider morning check-ins too!")
    
    return insights[:5]  # Return top 5 insights

@app.route('/api/mood_data')
@login_required
def api_mood_data():
    """API endpoint for mood chart data"""
    days = int(request.args.get('days', 30))
    start_date = datetime.utcnow() - timedelta(days=days)
    
    moods = MoodEntry.query.filter(
        MoodEntry.user_id == current_user.id,
        MoodEntry.timestamp >= start_date
    ).order_by(MoodEntry.timestamp.asc()).all()
    
    # Group by date
    mood_by_date = defaultdict(list)
    for mood in moods:
        date_key = mood.timestamp.date().isoformat()
        mood_by_date[date_key].append(mood.mood_score)
    
    # Calculate daily averages
    chart_data = []
    for date_str, scores in mood_by_date.items():
        avg_score = sum(scores) / len(scores)
        chart_data.append({
            'date': date_str,
            'mood': round(avg_score, 1),
            'entries': len(scores)
        })
    
    return jsonify(chart_data)

# Add this route for meditation session tracking
@app.route('/meditation/complete', methods=['POST'])
@login_required
def complete_meditation():
    """Track completed meditation session"""
    try:
        duration = int(request.form.get('duration', 0))  # in minutes
        meditation_type = request.form.get('type', 'general')
        
        # Record progress
        progress = UserProgress(
            user_id=current_user.id,
            metric_name='meditation_minutes',
            metric_value=duration,
            date=datetime.utcnow().date(),
            notes=f'Completed {duration}-minute {meditation_type} meditation'
        )
        
        db.session.add(progress)
        db.session.commit()
        
        # Check for meditation goals and update them
        meditation_goals = Goal.query.filter_by(
            user_id=current_user.id,
            category='meditation',
            is_completed=False
        ).all()
        
        for goal in meditation_goals:
            if 'daily' in goal.title.lower() or 'minute' in goal.title.lower():
                goal.current_value += duration
                if goal.target_value and goal.current_value >= goal.target_value:
                    goal.is_completed = True
                    flash(f'🎉 Goal completed: {goal.title}')
        
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': f'Meditation session recorded! +{duration} minutes'})
    
    except Exception as e:
        logger.error(f"Error recording meditation: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to record session'})




if __name__ == '__main__':
    # Create tables if they don't exist
    with app.app_context():
        db.create_all()
    
    # Get port from environment variable (Render provides this)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)