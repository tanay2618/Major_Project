from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, Base, get_db
import models
import schemas
import auth

# Create database tables automatically if they don't exist in Supabase
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Deepfake-Resistant Video KYC Backend",
    version="1.0.0"
)

# Enable CORS for React frontend (Vite default port: 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Seed default demo accounts on startup
@app.on_event("startup")
def seed_demo_accounts():
    db = next(get_db())
    try:
        # Check Applicant
        applicant = db.query(models.User).filter(models.User.email == "user@demo.com").first()
        if not applicant:
            db.add(models.User(
                full_name="Demo Applicant",
                email="user@demo.com",
                hashed_password=auth.hash_password("user123"),
                role=models.UserRole.APPLICANT
            ))

        # Check Officer
        officer = db.query(models.User).filter(models.User.email == "officer@demo.com").first()
        if not officer:
            db.add(models.User(
                full_name="Demo KYC Officer",
                email="officer@demo.com",
                hashed_password=auth.hash_password("officer123"),
                role=models.UserRole.OFFICER
            ))
        db.commit()
    finally:
        db.close()

@app.get("/")
def root():
    return {"status": "online", "message": "Deepfake-Resistant Video KYC API Running"}

# User Registration Endpoint
@app.post("/api/auth/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    new_user = models.User(
        full_name=user_data.full_name,
        email=user_data.email,
        hashed_password=auth.hash_password(user_data.password),
        role=user_data.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = auth.create_access_token({"sub": str(new_user.id), "role": new_user.role})
    return {"access_token": token, "token_type": "bearer", "user": new_user}

# User Login Endpoint
@app.post("/api/auth/login", response_model=schemas.Token)
def login(login_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user or not auth.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    token = auth.create_access_token({"sub": str(user.id), "role": user.role})
    return {"access_token": token, "token_type": "bearer", "user": user}