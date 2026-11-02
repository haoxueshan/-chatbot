import argparse
import getpass
import os
import sys
from app.db import SessionLocal, init_db
from app.models import User, LoginSession
from app.api.auth import hasher


def main():
    parser=argparse.ArgumentParser(description='ClassBridge private administrator setup')
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create-admin');create.add_argument('--username',default='admin');create.add_argument('--reset-password',action='store_true')
    commands.add_parser('init-db')
    args=parser.parse_args()
    if args.command=='init-db':init_db();print('Database initialized. Production migrations: alembic upgrade head');return
    password=os.environ.get('CLASSBRIDGE_ADMIN_PASSWORD')
    if not password:
        password=getpass.getpass('Administrator password (at least 12 characters): ')
        if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords do not match')
    if len(password)<12:raise SystemExit('Password must contain at least 12 characters')
    init_db()
    with SessionLocal() as db:
        existing=db.query(User).filter_by(username=args.username).first()
        if existing and not args.reset_password:raise SystemExit('Account already exists. Use --reset-password explicitly.')
        if existing:
            existing.password_hash=hasher.hash(password)
            db.query(LoginSession).filter_by(user_id=existing.id).delete()
        else:db.add(User(username=args.username,password_hash=hasher.hash(password)))
        db.commit()
    print(f'Administrator {args.username} is ready. Public registration is disabled.')


if __name__=='__main__':main()
