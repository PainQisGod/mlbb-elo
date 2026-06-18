# Elo.py
import datetime
import pandas as pd
import streamlit as st
import io
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

# New table to store dynamic app configurations like the leaderboard date
class AppConfig(Base):
    __tablename__ = "app_config"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)

# --- SAFE STRUCTURE AUTO-REPAIR ---
inspector = inspect(engine)
if "match_history" in inspector.get_table_names():
    columns = [c["name"] for c in inspector.get_columns("match_history")]
    if "team_a" not in columns:
        MatchHistory.__table__.drop(bind=engine, checkfirst=True)

Base.metadata.create_all(bind=engine)

# Seed default settings if empty
db = SessionLocal()
if db.query(League).count() == 0:
    default_leagues = ["MPL Indonesia", "MPL Cambodia", "MPL Philippines", "MPL Malaysia", "International / Other"]
    for lg in default_leagues:
        db.add(League(name=lg))
    db.commit()

# Default date initialization if missing
if db.query(AppConfig).filter(AppConfig.key == "leaderboard_date").count() == 0:
    db.add(AppConfig(key="leaderboard_date", value=datetime.date.today().strftime("%B %d, %Y")))
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
# Fetch the saved leaderboard date
saved_date_obj = db.query(AppConfig).filter(AppConfig.key == "leaderboard_date").first()
LEADERBOARD_DATE = saved_date_obj.value if saved_date_obj else "Unknown"
db.close()

# ==========================================
# 4. CONDITIONAL MAIN PAGE ROUTING
# ==========================================

if app_mode == "📊 Public Dashboard":
    st.title("🏆 MLBB Esports Elo Standings")
    st.markdown(f"##### *Dynamic power rankings data up to date as of: **{LEADERBOARD_DATE}***")
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
    st.title("🧮 Elo Match Calculator & Bulk Loader")
    
    calc_tab1, calc_tab2 = st.tabs(["📝 Single Manual Entry", "📋 Paste Raw Text Logs"])
    
    with calc_tab1:
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
                    st.success(f"🎉 Match between {team_a_name} and {team_b_name} calculated and logged!")
                    st.rerun() 
                except Exception as e:
                    st.error(f"Database Exception: {e}")
                finally:
                    db.close()
                    
    with calc_tab2:
        st.subheader("🚀 Mass Processing Module (Direct Paste)")
        st.markdown("""
        Copy the raw match logs block text from your chat window and paste it directly into the input area below.
        """)
        
        with st.expander("📊 Show Required Header Format"):
            st.markdown("""
            Ensure your pasted block text begins with this exact header line:
            ```text
            team_a,team_b,league_a,league_b,score_a,score_b,stage
            ```
            """)
            
        pasted_data = st.text_area(
            "Paste Raw Text Logs Data Here:", 
            placeholder="team_a,team_b,league_a,league_b,score_a,score_b,stage\n...",
            height=300
        )
        
        if pasted_data.strip():
            try:
                df = pd.read_csv(io.StringIO(pasted_data.strip()))
                
                st.write("📋 **Previewing parsed data entries:**")
                st.dataframe(df.head(10), use_container_width=True)
                
                required_cols = ["team_a", "team_b", "league_a", "league_b", "score_a", "score_b", "stage"]
                missing_cols = [c for c in required_cols if c not in df.columns]
                
                if missing_cols:
                    st.error(f"❌ Missing required formatting headers: {missing_cols}")
                else:
                    if st.button("⚡ Execute Bulk Process Pipeline", use_container_width=True):
                        db = SessionLocal()
                        success_count = 0
                        
                        for idx, row in df.iterrows():
                            if int(row['score_a']) == int(row['score_b']):
                                continue
                                
                            ta_name = str(row['team_a']).strip()
                            tb_name = str(row['team_b']).strip()
                            lg_a = str(row['league_a']).strip()
                            lg_b = str(row['league_b']).strip()
                            sc_a = int(row['score_a'])
                            sc_b = int(row['score_b'])
                            stg = str(row['stage']).strip().upper()
                            
                            t_a = db.query(Team).filter(Team.name == ta_name).first()
                            if not t_a:
                                t_a = Team(name=ta_name, region=lg_a, current_elo=1500.0)
                                db.add(t_a); db.flush()
                                
                            t_b = db.query(Team).filter(Team.name == tb_name).first()
                            if not t_b:
                                t_b = Team(name=tb_name, region=lg_b, current_elo=1500.0)
                                db.add(t_b); db.flush()
                                
                            old_a, old_b = t_a.current_elo, t_b.current_elo
                            new_elo_a, new_elo_b = calculate_elo_shift(old_a, old_b, sc_a, sc_b, stg)
                            
                            t_a.current_elo = new_elo_a
                            t_b.current_elo = new_elo_b
                            
                            if sc_a > sc_b:
                                t_a.wins += 1; t_b.losses += 1
                            elif sc_b > sc_a:
                                t_b.wins += 1; t_a.losses += 1
                                
                            history_entry = MatchHistory(
                                team_a=ta_name, team_b=tb_name,
                                league_a=lg_a, league_b=lg_b,
                                score_a=sc_a, score_b=sc_b,
                                old_elo_a=old_a, old_elo_b=old_b,
                                new_elo_a=new_elo_a, new_elo_b=new_elo_b,
                                stage=stg
                            )
                            db.add(history_entry)
                            success_count += 1
                            
                        db.commit()
                        db.close()
                        st.success(f"🚀 Successfully processed {success_count} matches directly from text paste!")
                        st.rerun()
            except Exception as e:
                st.error(f"❌ Error decoding text lines: {e}")

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
                    
        st.markdown("---")
        
        st.subheader("📝 Rebrand or Merge Registered Team")
        if not team_names_list:
            st.info("No registered teams available to modify.")
        else:
            old_team_selection = st.selectbox("Select Team to Modify:", team_names_list)
            
            # Choose between simple text rebrand or deep database merge
            manage_mode = st.radio("Management Type:", ["Simple Rebrand (Change Name)", "Deep Database Merge (Combine Duplicates)"])
            
            if manage_mode == "Simple Rebrand (Change Name)":
                new_team_name = st.text_input("Enter New Name Designation:", placeholder="e.g. Fnatic ONIC").strip()
                
                if st.button("🔄 Apply Name Rebrand", use_container_width=True):
                    if not new_team_name:
                        st.error("❌ New name cannot be blank.")
                    elif new_team_name in team_names_list:
                        st.error("❌ This team name already exists in database registry. Use Merge mode instead!")
                    else:
                        db = SessionLocal()
                        try:
                            team_obj = db.query(Team).filter(Team.name == old_team_selection).first()
                            if team_obj:
                                team_obj.name = new_team_name
                                
                                matches_as_a = db.query(MatchHistory).filter(MatchHistory.team_a == old_team_selection).all()
                                for m in matches_as_a:
                                    m.team_a = new_team_name
                                    
                                matches_as_b = db.query(MatchHistory).filter(MatchHistory.team_b == old_team_selection).all()
                                for m in matches_as_b:
                                    m.team_b = new_team_name
                                    
                                db.commit()
                                st.success(f"✅ Successfully rebranded '{old_team_selection}' to '{new_team_name}'!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error during rebrand execution: {e}")
                        finally:
                            db.close()
            
            elif manage_mode == "Deep Database Merge (Combine Duplicates)":
                target_team_selection = st.selectbox("Select Target Team to Merge Records Into:", [name for name in team_names_list if name != old_team_selection])
                st.warning(f"⚠️ Warning: This will move all match histories from '{old_team_selection}' over to '{target_team_selection}', add up their total records, and delete the '{old_team_selection}' entry permanently.")
                
                if st.button("🔗 Execute Deep Database Merge Pipeline", use_container_width=True):
                    db = SessionLocal()
                    try:
                        source_obj = db.query(Team).filter(Team.name == old_team_selection).first()
                        target_obj = db.query(Team).filter(Team.name == target_team_selection).first()
                        
                        if source_obj and target_obj:
                            # 1. Update match logs histories where team acted as team_a
                            matches_a = db.query(MatchHistory).filter(MatchHistory.team_a == old_team_selection).all()
                            for m in matches_a:
                                m.team_a = target_team_selection
                                
                            # 2. Update match logs histories where team acted as team_b
                            matches_b = db.query(MatchHistory).filter(MatchHistory.team_b == old_team_selection).all()
                            for m in matches_b:
                                m.team_b = target_team_selection
                                
                            # 3. Sum up the historical statistics records
                            target_obj.wins += source_obj.wins
                            target_obj.losses += source_obj.losses
                            
                            # 4. Wipe out the duplicate source table registration row
                            db.delete(source_obj)
                            db.commit()
                            st.success(f"✅ Merged completely! Everything shifted into '{target_team_selection}'.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error during deep merge execution: {e}")
                    finally:
                        db.close()
                    
    with col2:
        st.subheader("📅 Update Leaderboard Date Context")
        user_date_text = st.text_input("Standings 'As Of' Date Label:", value=LEADERBOARD_DATE, placeholder="e.g. March 2026, Post MPL Week 3")
        if st.button("💾 Save Leaderboard Date Stamp", use_container_width=True):
            db = SessionLocal()
            config_obj = db.query(AppConfig).filter(AppConfig.key == "leaderboard_date").first()
            if config_obj:
                config_obj.value = user_date_text
                db.commit()
                st.success("✅ Main leaderboard date description successfully updated!")
                st.rerun()
            db.close()
            
        st.markdown("---")
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
