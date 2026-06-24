"""Promote a phone number to admin (or create it as admin if new).

Usage:
    python make_admin.py 09123456789
"""
import sys
import db


def main():
    if len(sys.argv) != 2:
        print("Usage: python make_admin.py <phone>")
        sys.exit(1)
    phone = sys.argv[1].strip()
    db.init_db()
    db.get_or_create_user(phone)
    db.mark_user_verified(phone)
    db.set_admin(phone, True)
    print(f"OK: {phone} is now an admin.")


if __name__ == "__main__":
    main()
