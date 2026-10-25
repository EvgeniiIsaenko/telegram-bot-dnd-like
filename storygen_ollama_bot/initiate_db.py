import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, UniqueConstraint, func  # connection to db, field types
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, deferred  # model class, session for transactions, relationship for table connection, deferred to avoid loading a bunch of text with a call

load_dotenv()
Base = declarative_base()

engine = create_engine(os.getenv('DATABASE_LINK'), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)  # bind to engine for transactions

# table of Users
class Users(Base):
    __tablename__   = 'users'
    id              = Column(Integer, primary_key=True)  # id int pri key
    tg_id           = Column(BigInteger, unique=True, nullable=False, index=True)  # id telegram
    username        = Column(String(255), unique=True, nullable=False)  # username str NOT NULL
    name            = Column(String(255)) # name str
    gender          = Column(String(1), nullable=False)  # gender string NOT NULL
    about           = deferred(Column(Text))  # about text    # deferred to avoid loading it fully
    level           = Column(Integer, nullable=False, default=1) # level int NOT NULL DEFAULT = 1
    xp              = Column(Integer, nullable=False, default=0) # xp int NOT NULL DEFAULT = 0
    hp              = Column(Integer, nullable=False, default=20)  # hp int NOT NULL DEFAULT = 20
    last_visit      = Column(DateTime)  # last_visit datetime
    reg_date        = Column(DateTime, server_default=func.now())  # reg_date datetime the moment user registers

# table of Item
class Item(Base):
    __tablename__   = 'item'
    id              = Column(Integer, primary_key=True)  # id int pri key
    name            = Column(String(255), unique=True, nullable=False)  # name str UNIQUE NOT NULL
    about           = Column(Text)  # about text

# table of Inventory Item
class InventoryItem(Base):
    __tablename__   = 'inventory'
    __table_args__  = (UniqueConstraint('user_id', 'item_id', name='uq_inventory_user_item'),) # unique constraint to make distinct items
    id              = Column(Integer, primary_key=True)  # id int pri key
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True) # user_id int FK CASCADE DELETE NOT NULL INDEX
    item_id         = Column(Integer, ForeignKey("item.id"), nullable=False) # item_id int FK NOT NULL
    quantity        = Column(Integer, nullable=False, default=1) # quantity int NOT NULL DEFAULT = 1
    item            = relationship('Item') # related to item class


# table of Story Message
class StoryMessage(Base):
    __tablename__   = 'story'
    id              = Column(Integer, primary_key=True) # id int pri key
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True) # user_id FK CASCADE NOT NULL INDEX
    role            = Column(String(16), nullable=False)  # role str NOT NULL # shows who the author of the message was
    content         = Column(Text, nullable=False) # content text # current content
    created_at      = Column(DateTime, server_default=func.now()) # created_at datetime nww o by default

def init_db():
    Base.metadata.create_all(engine)
 
 
if __name__ == "__main__":
    ## init
    # py initiate_db.py         
    ## reset EVERYTHING DO NOT PULL THIS IF YOU DONT WANT YOUR DATA TO BE DESTROYED
    # py initiate_db.py reset
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        Base.metadata.drop_all(engine)
        print("Tables created.")
    init_db()
    print("Tables created.")
