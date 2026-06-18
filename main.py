# main.py
import datetime
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc
from sqlalchemy.orm import declarative_base, sessionmaker

# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================
DATABASE_URL = "sqlite:///./mlbb_elo_database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Tables
class Team(Base):
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    region = Column(String, default="Unknown")
    current_elo = Column(Float, default=1500.0)  # Every team starts at exactly 1500
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)

class MatchHistory(Base):
    __tablename__ = "match_history"
    
    id = Column(Integer, primary_key=True, index=True)
    team_a_name = Column(String, nullable=False)
    team_b_name = Column(String, nullable=False)
    score_a = Column(Integer, nullable=False)
    score_b = Column(Integer, nullable=False)
    team_a_old_elo = Column(Float, nullable=False)
    team_b_old_elo = Column(Float, nullable=False)
    team_a_new_elo = Column(Float, nullable=False)
    team_b_new_elo = Column(Float, nullable=False)
    stage = Column(String, nullable=False)
    played_at = Column(DateTime, default=datetime.datetime.utcnow)

# Create tables in SQLite
Base.metadata.create_all(bind=engine)

# ==========================================
# 2. FASTAPI SETUP & CORS SECURITY
# ==========================================
app = FastAPI(title="MLBB Elo Engine")

# This allows your index.html file to talk to your backend safely
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 3. API REQUEST & RESPONSE SCHEMAS
# ==========================================
class MatchInput(BaseModel):
    team_a_name: str
    team_b_name: str
    score_a: int
    score_b: int
    region_a: str = "Unknown"  
    region_b: str = "Unknown"  
    stage: str                 # "REGULAR_SEASON", "PLAYOFFS", "INTERNATIONAL"

class StandingRow(BaseModel):
    rank: int
    name: str
    region: str
    elo: float
    record: str
    regional_rank: int

# ==========================================
# 4. CORE ELO LOGIC ENGINE
# ==========================================
def calculate_elo_shift(elo_a: float, elo_b: float, score_a: int, score_b: int, stage: str):
    # Match weighting (K-Factor)
    k_factors = {"REGULAR_SEASON": 32, "PLAYOFFS": 48, "INTERNATIONAL": 64}
    k = k_factors.get(stage.upper(), 32)
    
    # Margin multiplier (gives extra weight to clean sweeps)
    margin = abs(score_a - score_b)
    margin_multiplier = 1.5 if margin == 3 else (1.25 if margin == 2 else 1.0)
    k *= margin_multiplier
    
    # Actual outcome
    actual_a = 1.0 if score_a > score_b else 0.0
    actual_b = 1.0 - actual_a
    
    # Expected outcome formulas
    expected_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    expected_b = 1 / (1 + 10 ** ((elo_a - elo_b) / 400))
    
    # Compute new ratings
    new_a = elo_a + k * (actual_a - expected_a)
    new_b = elo_b + k * (actual_b - expected_b)
    
    return round(new_a, 2), round(new_b, 2)

# ==========================================
# 5. API ROUTES
# ==========================================
@app.get("/standings", response_model=List[StandingRow])
def get_standings():
    """Fetches all teams, sorts by Elo, and builds global and regional ranks."""
    db = SessionLocal()
    try:
        teams = db.query(Team).order_by(desc(Team.current_elo)).all()
        
        region_trackers = {}
        leaderboard = []
        
        for index, team in enumerate(teams):
            reg = team.region.upper()
            region_trackers[reg] = region_trackers.get(reg, 0) + 1
            
            leaderboard.append({
                "rank": index + 1,
                "name": team.name,
                "region": team.region,
                "elo": team.current_elo,
                "record": f"{team.wins}W-{team.losses}L",
                "regional_rank": region_trackers[reg]
            })
        return leaderboard
    finally:
        db.close()

@app.post("/matches")
def record_match(match: MatchInput):
    """Saves match, updates team records, and automatically handles brand new teams."""
    if match.score_a == match.score_b:
        raise HTTPException(status_code=400, detail="MLBB matches cannot end in a tie series.")
        
    db = SessionLocal()
    try:
        # 1. Fetch or dynamically auto-create Team A (starts at 1500)
        team_a = db.query(Team).filter(Team.name == match.team_a_name).first()
        if not team_a:
            team_a = Team(name=match.team_a_name, region=match.region_a, current_elo=1500.0)
            db.add(team_a)
            db.flush() 
            
        # 2. Fetch or dynamically auto-create Team B (starts at 1500)
        team_b = db.query(Team).filter(Team.name == match.team_b_name).first()
        if not team_b:
            team_b = Team(name=match.team_b_name, region=match.region_b, current_elo=1500.0)
            db.add(team_b)
            db.flush()

        # Save previous scores for history logs
        old_elo_a = team_a.current_elo
        old_elo_b = team_b.current_elo
        
        # 3. Process Elo changes
        new_elo_a, new_elo_b = calculate_elo_shift(
            old_elo_a, old_elo_b, match.score_a, match.score_b, match.stage
        )
        
        # 4. Update core records
        team_a.current_elo = new_elo_a
        team_b.current_elo = new_elo_b
        
        if match.score_a > match.score_b:
            team_a.wins += 1
            team_b.losses += 1
        else:
            team_a.losses += 1
            team_b.wins += 1
            
        # 5. Save details into historical logs
        history_entry = MatchHistory(
            team_a_name=team_a.name, team_b_name=team_b.name,
            score_a=match.score_a, score_b=match.score_b,
            team_a_old_elo=old_elo_a, team_b_old_elo=old_elo_b,
            team_a_new_elo=new_elo_a, team_b_new_elo=new_elo_b,
            stage=match.stage
        )
        db.add(history_entry)
        
        db.commit()
        return {
            "status": "Success",
            "team_a": {"name": team_a.name, "old_elo": old_elo_a, "new_elo": new_elo_a},
            "team_b": {"name": team_b.name, "old_elo": old_elo_b, "new_elo": new_elo_b}
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()