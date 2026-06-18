# Elo.py
import datetime
import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

# ==========================================
# 1. DATABASE CONFIGURATION (SQLite)
# ==========================================
DATABASE_URL = "sqlite:///mlbb_elo_database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    region = Column(String, default="International / Other")  
    current_elo = Column(Float, default=1500.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)

class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

class MatchHistory(Base):
    __tablename__ = "match_history"
    id = Column(Integer, primary_key=True, index=True)
    team_a = Column(String, nullable=False)
    team_b = Column(String, nullable=False)
    league_a = Column(String, nullable=False)
    league_b = Column(String, nullable=False)
    score_a = Column(Integer, nullable=False)
    score_b = Column(Integer, nullable=False)
    old_elo_a = Column(Float, nullable=False)
    old_elo_b = Column(Float, nullable=False)
    new_elo_a = Column(Float, nullable=False)
    new_elo_b = Column(Float, nullable=False)
    stage = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

# --- SAFE STRUCTURE AUTO-REPAIR ---
inspector = inspect(engine)
if "match_history" in inspector.get_table_names():
    columns = [c["name"] for c in inspector.get_columns("match_history")]
    if "team_a" not in columns:
        MatchHistory.__table__.drop(bind=engine, checkfirst=True)

Base.metadata.create_all(bind=engine)

# Seed default leagues if empty
db = SessionLocal()
if db.query(League).count() == 0:
    default_leagues = ["MPL Indonesia", "MPL Cambodia", "MPL Philippines", "MPL Malaysia", "International / Other"]
    for lg in default_leagues:
        db.add(League(name=lg))
    db.commit()
db.close()

# ==========================================
# 2. CORE ELO ENGINE LOGIC
# ==========================================
def calculate_elo_shift(elo_a: float, elo_b: float, score_a: int, score_b: int, stage: str):
    k_factors = {"REGULAR_SEASON": 32, "PLAYOFFS": 48, "INTERNATIONAL": 64}
    k = k_factors.get(stage.upper(), 32)
    
    margin = abs(score_a - score_b)
    margin_multiplier = 1.5 if margin == 3 else (1.25 if margin == 2 else 1.0)
    k *= margin_multiplier
    
    if score_a == score_b:
        actual_a = 0.5
        actual_b = 0.5
    else:
        actual_a = 1.0 if score_a > score_b else 0.0
        actual_b = 1.0 - actual_a
    
    expected_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    expected_b = 1 / (1 + 10 ** ((elo_a - elo_b) / 400))
    
    new_a = elo_a + k * (actual_a - expected_a)
    new_b = elo_b + k * (actual_b - expected_b)
    return round(new_a, 2), round(new_b, 2)

# ==========================================
# 3. STREAMLIT APP CONFIGURATION & NAVIGATION
# ==========================================
st.set_page_config(page_title="MLBB Power Rankings Engine", layout="wide")

st.sidebar.title("🕹️ Dashboard Control")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if st.session_state.authenticated:
    app_mode = st.sidebar.radio("Select Interface Module:", [
        "📊 Public Dashboard",
        "🧮 Elo Match Calculator", 
        "⚙️ League & Team Management"
    ])
    if st.sidebar.button("🔒 Log Out of Admin Mode", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
else:
    st.sidebar.info("💡 Public View Mode active. Enter the password on the main screen to modify records.")
    app_mode = "📊 Public Dashboard"

# Fetch configurations
db = SessionLocal()
all_leagues_db = db.query(League).order_by(League.name).all()
LEAGUE_OPTIONS = [lg.name for lg in all_leagues_db]
all_registered_teams = db.query(Team).order_by(Team.name).all()
team_names_list = [team.name for team in all_registered_teams]
db.close()

# ==========================================
# 4. CONDITIONAL MAIN PAGE ROUTING
# ==========================================

if app_mode == "📊 Public Dashboard":
    st.title("🏆 MLBB Esports Elo Standings")
    st.markdown("##### *Only professional league and international tournaments count*")
    st.caption("Real-time team dynamic power rankings and global match log histories.")
    
    db = SessionLocal()
    all_teams = db.query(Team).order_by(desc(Team.current_elo)).all()
    
    try:
        all_matches = db.query(MatchHistory).order_by(desc(MatchHistory.timestamp)).all()
    except Exception:
        all_matches = []
        
    db.close()
    
    if not all_teams:
        st.info("💡 Your tracking ledger is empty. Use the Login section below to get started!")
    else:
        tab_titles = ["🌎 Global Circuit"] + [f"🏆 {lg}" for lg in LEAGUE_OPTIONS]
        ui_tabs = st.tabs(tab_titles)
        
        def display_dashboard_content(filtered_teams, league_filter_name=None):
            col1, col2 = st.columns([3, 2])
            
            with col1:
                st.subheader("📋 Standings Leaderboard")
                if not filtered_teams:
                    st.write("No team entry stats recorded inside this division.")
                else:
                    table_rows = []
                    for rank, t in enumerate(filtered_teams, start=1):
                        table_rows.append({
                            "Rank": rank,
                            "Team Name": t.name,
                            "League / Region": t.region,
                            "Elo Metric": t.current_elo,
                            "Record Details": f"{t.wins}W - {t.losses}L"
                        })
                    st.dataframe(table_rows, use_container_width=True, hide_index=True)
            
            with col2:
                st.subheader("⏱️ Recent Match Logs")
                if league_filter_name:
                    filtered_matches = [m for m in all_matches if m.league_a == league_filter_name or m.league_b == league_filter_name]
                else:
                    filtered_matches = all_matches

                if not filtered_matches:
                    st.write("No recent series logs recorded here yet.")
                else:
                    # Updated to only fetch the slice of top 5 latest elements
                    for m in filtered_matches[:5]:
                        st.markdown(f"""
                        > **{m.team_a}** `{m.score_a}` vs `{m.score_b}` **{m.team_b}** > *Context:* `{m.stage}` | {m.timestamp.strftime('%Y-%m-%d %H:%M')}  
                        > *Elo Shift:* {m.team_a} ({m.old_elo_a} → **{m.new_elo_a}**) | {m.team_b} ({m.old_elo_b} → **{m.new_elo_b}**)
                        """)
                        st.markdown("---")

        with ui_tabs[0]:
            display_dashboard_content(all_teams, league_filter_name=None)
            
        for idx, league_name in enumerate(LEAGUE_OPTIONS, start=1):
            with ui_tabs[idx]:
                filtered = [team for team in all_teams if team.region == league_name]
                display_dashboard_content(filtered, league_filter_name=league_name)

    if not st.session_state.authenticated:
        st.markdown("<br><br><br><hr>", unsafe_allow_html=True)
        st.subheader("Ancillary Node Gate")
        entered_password = st.text_input("Enter Admin Password to execute updates:", type="password")
        if st.button("Unlock Admin Dashboard Tools", use_container_width=True):
            try:
                correct_password = st.secrets["ADMIN_PASSWORD"]
            except Exception:
                correct_password = "admin"
                
            if entered_password == correct_password:
                st.session_state.authenticated = True
                st.success("Access Granted! Admin modules are now ready.")
                st.rerun()
            else:
                st.error("❌ Invalid password token.")

elif app_mode == "🧮 Elo Match Calculator":
    st.title("🧮 Dynamic Elo Match Calculator")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔵 Team A (Home)")
        team_a_name = st.text_input("Team A Name", placeholder="e.g. RRQ Hoshi").strip()
        league_a = st.selectbox("Team A League", LEAGUE_OPTIONS, key="l_a")
        score_a = st.number_input("Team A Maps Won", min_value=0, max_value=4, value=0, key="s_a")
        
    with col2:
        st.subheader("🔴 Team B (Away)")
        team_b_name = st.text_input("Team B Name", placeholder="e.g. See You Soon").strip()
        league_b = st.selectbox("Team B League", LEAGUE_OPTIONS, key="l_b")
        score_b = st.number_input("Team B Maps Won", min_value=0, max_value=4, value=0, key="s_b")
        
    st.markdown("---")
    match_stage = st.selectbox("Tournament Context", ["REGULAR_SEASON", "PLAYOFFS", "INTERNATIONAL"])
    
    if st.button("💾 Run Calculation & Save History", use_container_width=True):
        if not team_a_name or not team_b_name:
            st.error("❌ Both team names must be entered.")
        else:
            db = SessionLocal()
            try:
                t_a = db.query(Team).filter(Team.name == team_a_name).first()
                if not t_a:
                    t_a = Team(name=team_a_name, region=league_a, current_elo=1500.0)
                    db.add(t_a); db.flush()
                    
                t_b = db.query(Team).filter(Team.name == team_b_name).first()
                if not t_b:
                    t_b = Team(name=team_b_name, region=league_b, current_elo=1500.0)
                    db.add(t_b); db.flush()
                
                old_a, old_b = t_a.current_elo, t_b.current_elo
                new_elo_a, new_elo_b = calculate_elo_shift(old_a, old_b, score_a, score_b, match_stage)
                
                t_a.current_elo = new_elo_a
                t_b.current_elo = new_elo_b
                
                if score_a > score_b:
                    t_a.wins += 1; t_b.losses += 1
                elif score_b > score_a:
                    t_b.wins += 1; t_a.losses += 1
                
                history_entry = MatchHistory(
                    team_a=team_a_name, team_b=team_b_name,
                    league_a=league_a, league_b=league_b,
                    score_a=score_a, score_b=score_b,
                    old_elo_a=old_a, old_elo_b=old_b,
                    new_elo_a=new_elo_a, new_elo_b=new_elo_b,
                    stage=match_stage
                )
                db.add(history_entry)
                db.commit()
                st.success(f"🎉 Match between {team_a_name} and {team_b_name} calculated and logged successfully!")
                st.rerun() 
            except Exception as e:
                st.error(f"Database Exception: {e}")
            finally:
                db.close()

elif app_mode == "⚙️ League & Team Management":
    st.title("⚙️ League & Team Management Console")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("➕ Create New League Route")
        new_league_name = st.text_input("New League Designation Name").strip()
        if st.button("✨ Register New League"):
            if not new_league_name:
                st.error("❌ League name cannot be blank.")
            elif new_league_name in LEAGUE_OPTIONS:
                st.error("❌ League already registered.")
            else:
                db = SessionLocal()
                try:
                    db.add(League(name=new_league_name))
                    db.commit()
                    st.success(f"✅ League '{new_league_name}' built!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    db.close()
                    
    with col2:
        st.subheader("🗑️ Database Purge Panel")
        if not team_names_list:
            st.info("No teams in system memory.")
        else:
            target_team_to_remove = st.selectbox("Select Profile to Delete:", team_names_list)
            confirm_deletion = st.checkbox(f"Confirm permanent deletion.")
            if st.button("❌ Wipe Team"):
                if not confirm_deletion:
                    st.warning("⚠️ Verify checkbox first.")
                else:
                    db = SessionLocal()
                    try:
                        db.query(Team).filter(Team.name == target_team_to_remove).delete()
                        db.commit()
                        st.success(f"💥 Purged!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Purge fault: {e}")
                    finally:
                        db.close()
