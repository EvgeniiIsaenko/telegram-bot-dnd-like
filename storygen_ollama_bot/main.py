import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, ForeignKey, text # connection to db, field types + text for extra func
from sqlalchemy.ext.declarative import declarative_base # model class
from sqlalchemy.orm import sessionmaker, relationship, deferred # session for transactions, relationship for table connection, deferrd to avoid loading a bunch of text with a call

Base = declarative_base()

engine = create_engine(os.getenv('DATABASE_LINK'))
Session = sessionmaker(bind=engine) # bind to engine for transactions
session = Session()

# table of Users
class Users(Base):
    __tablename__ = 'users'
    id          = Column(Integer, primary_key=True) # id int pri key
    username    = Column(String(255), unique=True, nullable=False) # username str NOT NULL
    name        = Column(String(255))
    gender      = Column(String(1), nullable=False) # gender str(1) NOT NULL
    about       = deferred(Column(Text)) # about text    # deferred to avoid loading it fully
    last_visit  = Column(DateTime) # last_visit datetime
    reg_date    = Column(DateTime, server_default=text('NOW()')) # reg_date datetime the moment user registers


# table of Inventory Item
class InventoryItem(Base):
    __tablename__ = 'inventory'
    id      = Column(Integer, primary_key=True) # id int pri key
    user_id = Column(Integer, nullable=False) # user_id int
    item_id = Column(Integer, nullable=False) # item_id int
    item = relationship('Item')

# table of Item
class Item(Base):
    id   = Column(Integer, primary_key=True) # id int pri key
    name = Column(String(255), unique=True, nullable=False) # name int UNIQUE NOT NULL
