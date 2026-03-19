from sqlalchemy.orm import Session

from app.models.user import User


def list_users(db: Session, q: str | None = None, limit: int = 10, offset: int = 0) -> list[User]:
    query = db.query(User)
    if q:
        query = query.filter(User.username.like(f"%{q}%"))
    return query.offset(offset).limit(limit).all()


def get_user(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, username: str, email: str | None) -> User:
    if db.query(User).filter(User.username == username).first():
        raise ValueError("username already exists")
    if email and db.query(User).filter(User.email == email).first():
        raise ValueError("email already exists")

    user = User(username=username, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, username: str | None, email: str | None) -> User | None:
    user = get_user(db, user_id)
    if not user:
        return None

    if username and username != user.username:
        if db.query(User).filter(User.username == username).first():
            raise ValueError("username already exists")
        user.username = username

    if email != user.email:
        if email and db.query(User).filter(User.email == email).first():
            raise ValueError("email already exists")
        user.email = email

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = get_user(db, user_id)
    if not user:
        return False

    db.delete(user)
    db.commit()
    return True
