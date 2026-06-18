# Elo.py
import datetime
import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc
from sqlalchemy.orm import declarative_base, sessionmaker

# ==========================================
# 1. DATABASE CONFIGURATION (SQLite)
# ==========================================
DATABASE_URL = "sqlite:///./mlbb_elo_database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    region = Column(String, default="International / Other")  # Stores the league/region tag name
    current_elo = Column(Float, default=1500.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)

class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

Base.metadata.create_all(bind=engine)

# Seed default leagues if the league table is completely empty
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
app_mode = st.sidebar.radio("Select Interface Module:", [
    "🧮 Elo Match Calculator", 
    "📊 League Leaderboards",
    "⚙️ League & Team Management"
])

# Dynamically fetch current league options from database
db = SessionLocal()
all_leagues_db = db.query(League).order_by(League.name).all()
LEAGUE_OPTIONS = [lg.name for lg in all_leagues_db]

# Fetch current team list from DB for selections
all_registered_teams = db.query(Team).order_by(Team.name).all()
team_names_list = [team.name for team in all_registered_teams]
db.close()

# ==========================================
# MODULE 1: INTERACTIVE MATCH CALCULATOR
# ==========================================
if app_mode == "🧮 Elo Match Calculator":
    st.title("🧮 Dynamic Elo Match Calculator")
    st.caption("Input match metrics below to automatically re-score team power weight metrics.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔵 Team A (Home/Host)")
        team_a_name = st.text_input("Team A Name", placeholder="e.g. RRQ Hoshi", key="ta_name").strip()
        league_a = st.selectbox("Team A League", LEAGUE_OPTIONS, key="ta_league")
        score_a = st.number_input("Team A Maps Won", min_value=0, max_value=4, value=0, key="ta_score")
        
    with col2:
        st.subheader("🔴 Team B (Away/Challenger)")
        team_b_name = st.text_input("Team B Name", placeholder="e.g. See You Soon", key="tb_name").strip()
        league_b = st.selectbox("Team B League", LEAGUE_OPTIONS, key="tb_league")
        score_b = st.number_input("Team B Maps Won", min_value=0, max_value=4, value=0, key="tb_score")
        
    st.markdown("---")
    match_stage = st.selectbox("Tournament Lifecycle Context", ["REGULAR_SEASON", "PLAYOFFS", "INTERNATIONAL"])
    
    if st.button("💾 Run Calculation & Record Results", use_container_width=True):
        if not team_a_name or not team_b_name:
            st.error("❌ Both team names must be entered before calculating results.")
        elif score_a == score_b:
            st.error("❌ Tie sets are invalid; an outright series victor is required.")
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
                
                new_elo_a, new_elo_b = calculate_elo_shift(t_a.current_elo, t_b.current_elo, score_a, score_b, match_stage)
                
                t_a.current_elo = new_elo_a
                t_b.current_elo = new_elo_b
                if score_a > score_b:
                    t_a.wins += 1; t_b.losses += 1
                else:
                    t_b.wins += 1; t_a.losses += 1
                    
                db.commit()
                st.success(f"🎉 Result Recorded! {team_a_name} adjusted to {new_elo_a} | {team_b_name} adjusted to {new_elo_b}")
                st.rerun() 
            except Exception as e:
                st.error(f"Database Exception: {e}")
            finally:
                db.close()

# ==========================================
# MODULE 2: LEAGUE LEADERBOARDS
# ==========================================
elif app_mode == "📊 League Leaderboards":
    st.title("🏆 Professional Regional Standings")
    st.caption("Live power standings broken down across dynamically generated tournament leagues.")
    
    db = SessionLocal()
    all_teams = db.query(Team).order_by(desc(Team.current_elo)).all()
    db.close()
    
    if not all_teams:
        st.info("💡 Your tracking ledger is empty. Switch to the Match Calculator module to populate data rows.")
    else:
        # Create dynamic tabs based on the active leagues available
        tab_titles = ["🌎 Global Standings"] + [f"🏆 {lg}" for lg in LEAGUE_OPTIONS]
        ui_tabs = st.tabs(tab_titles)
        
        def display_leaderboard(filtered_teams):
            if not filtered_teams:
                st.write("No team matrix entries recorded inside this specific division framework.")
                return
            
            table_rows = []
            for rank, t in enumerate(filtered_teams, start=1):
                table_rows.append({
                    "Rank Placement": rank,
                    "Esports Organization": t.name,
                    "League / Region": t.region,
                    "Elo Strength Metric": t.current_elo,
                    "Wins": t.wins,
                    "Losses": t.losses,
                    "Record Details": f"{t.wins}W - {t.losses}L"
                })
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

        # Global Tab Layout
        with ui_tabs[0]:
            st.subheader("Global Consolidated Leaderboard Rankings")
            display_leaderboard(all_teams)
            
        # Dynamically map filter sets into each created region tab
        for idx, league_name in enumerate(LEAGUE_OPTIONS, start=1):
            with ui_tabs[idx]:
                st.subheader(f"{league_name} Leaderboard Standings")
                filtered = [team for team in all_teams if team.region == league_name]
                display_leaderboard(filtered)

# ==========================================
# MODULE 3: LEAGUE & TEAM MANAGEMENT (NEW)
# ==========================================
elif app_mode == "⚙️ League & Team Management":
    st.title("⚙️ League & Team Management Console")
    st.caption("Expand infrastructure frameworks by creating new leagues or removing data models manually.")
    
    col1, col2 = st.columns(2)
    
    # Left Column: Manage Leagues
    with col1:
        st.subheader("➕ Create New League Route")
        new_league_name = st.text_input("New League Designation Name", placeholder="e.g. MPL MENA").strip()
        if st.button("✨ Register New League"):
            if not new_league_name:
                st.error("❌ League designation name cannot be blank.")
            elif new_league_name in LEAGUE_OPTIONS:
                st.error("❌ This league is already registered inside the index tracker.")
            else:
                db = SessionLocal()
                try:
                    db.add(League(name=new_league_name))
                    db.commit()
                    st.success(f"✅ Active league '{new_league_name}' successfully built into the ecosystem framework!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error appending row: {e}")
                finally:
                    db.close()
                    
    # Right Column: Delete Profiles
    with col2:
        st.subheader("🗑️ Database Purge Panel")
        if not team_names_list:
            st.info("No active team profiles registered inside system memory.")
        else:
            target_team_to_remove = st.selectbox("Select Target Profile to Delete:", team_names_list)
            confirm_deletion = st.checkbox(f"Confirm permanent deletion of **{target_team_to_remove}**.")
            
            if st.button("❌ Wipe Selected Team From System"):
                if not confirm_deletion:
                    st.warning("⚠️ Check verification box step first.")
                else:
                    db = SessionLocal()
                    try:
                        db.query(Team).filter(Team.name == target_team_to_remove).delete()
                        db.commit()
                        st.success(f"💥 Profile row for '{target_team_to_remove}' purged!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Purge fault: {e}")
                    finally:
                        db.close()