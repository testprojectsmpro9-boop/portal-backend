import getpass
import sys

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.user import User, UserRole
from app.utils.security import hash_password, validate_password_strength


def main():
    print("Create an additional Super Admin")
    full_name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()

    if not full_name or not email:
        print("Name and email are required.")
        sys.exit(1)

    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(exc)
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print("That email already exists. No account was changed.")
            sys.exit(1)

        user = User(
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            must_change_password=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"Super Admin created successfully. User ID: {user.id}")
        print(f"Email: {user.email}")
        print(f"Role: {user.role.value}")
    except IntegrityError:
        db.rollback()
        print("Account was not created; the email may already exist.")
        sys.exit(1)
    except Exception:
        db.rollback()
        print("Account creation failed. Check server logs for details.")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
