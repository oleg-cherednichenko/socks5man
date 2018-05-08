import logging
from datetime import datetime

from socks5man.exceptions import Socks5manError
from socks5man.helpers import cwd

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Text, create_engine,
    Float
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

log = logging.getLogger(__name__)

Base = declarative_base()

class Socks5(Base):
    __tablename__ = "socks5s"

    id = Column(Integer(), primary_key=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer(), nullable=False)
    country = Column(String(255), nullable=False)
    country_code = Column(String(2), nullable=False)
    city = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    added_on = Column(DateTime(), default=datetime.now, nullable=False)
    last_use = Column(DateTime(), nullable=True)
    last_check = Column(DateTime(), nullable=True)
    operational = Column(Boolean, nullable=False, default=False)
    bandwidth = Column(Float(), nullable=True)
    connect_time = Column(Float(), nullable=True)
    description = Column(Text(), nullable=True)

    def __init__(self, host, port, country, country_code):
        self.host = host
        self.port = port
        self.country = country
        self.country_code = country_code

    def to_dict(self):
        """Converts object to dict.
        @param dt: encode datetime objects
        @return: dict
        """
        socks_dict = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                socks_dict[column.name] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                socks_dict[column.name] = value

        return socks_dict

    def __repr__(self):
        return "<Socks5(host=%s, port=%s, country=%s, authenticated=%s)>" % (
            self.host, self.port, self.country, (
                self.username is not None and self.password is not None
            )
        )

class Database(object):

    def __init__(self):
        self.connect()

    def connect(self):
        self.engine = create_engine("sqlite:///%s" % cwd("socks5man.db"))
        self.Session = sessionmaker(bind=self.engine)
        self._create()

    def _create(self):
        try:
            Base.metadata.create_all(self.engine)
        except SQLAlchemyError as e:
            raise Socks5manError("Failed to created database tables: %s" % e)

    def __del__(self):
        self.engine.dispose()

    def add_socks5(self, host, port, country, country_code, operational=False,
                   city=None, username=None, password=None, description=None):
        """Add new socks5 server to the database"""
        socks5 = Socks5(host, port, country, country_code)
        socks5.operational = operational
        socks5.city = city
        socks5.username = username
        socks5.password = password
        socks5.description = description

        session = self.Session()
        try:
            session.add(socks5)
            session.commit()
        except SQLAlchemyError as e:
            log.error("Error adding new socks5 to the database: %s", e)
            return False
        finally:
            session.close()
        return True

    def remove_socks5(self, id):
        """Removes the socks5 entry with the specified id"""
        session = self.Session()
        try:
            session.query(Socks5).filter_by(id=id).delete()
            session.commit()
        except SQLAlchemyError as e:
            log.error("Error while removing socks5 from the database: %s", e)
            return False
        finally:
            session.close()
        return True

    def list_socks5(self, country=None, country_code=None, city=None,
                    limit=500):

        session = self.Session()
        socks = session.query(Socks5)
        try:
            if country:
                socks = socks.filter_by(country=country)
            if country_code:
                socks = socks.filter_by(country_code=country_code)
            if city:
                socks = socks.filter_by(city=city)
            socks = socks.limit(limit).all()
            return socks
        except SQLAlchemyError as e:
            log.error("Error retrieving list of socks5s: %s", e)
            return []
        finally:
            session.close()

    def view_socks5(self, socks5_id):
        session = self.Session()
        socks5 = None
        try:
            socks5 = session.query(Socks5).get(socks5_id)
            if socks5:
                session.expunge(socks5)
        except SQLAlchemyError as e:
            log.error("Error finding socks5: %s", e)
        finally:
            session.close()
        return socks5

    def find_socks5(self, country=None, country_code=None, city=None,
                    min_mbps_down=None, max_connect_time=None, update_usage=True,
                    limit=1):
        """Find one or more matching socks5 servers matching the provided
        filters. Names etc should be in English
        @param country: The country
        @param country_code: 2 letter country code ISO 3166-1 alpha-2
        @param city: City to filter for
        @param min_mbps_down: Min Mbit/s the server should have (float)
        @param max_connect_time: Max average connection time to
         the server (float)
        @param update_usage: Should the last_used field be updated
         when finding a matching socks5? True by default
        @param limit: The maximum number of socks5s to find and return"""

        result = []
        session = self.Session()
        socks5 = session.query(Socks5)
        try:
            socks5 = socks5.filter_by(operational=True)
            if country:
                socks5 = socks5.filter_by(country=country)
            if country_code:
                socks5 = socks5.filter_by(country_code=country_code)
            if city:
                socks5 = socks5.filter_by(city=city)
            if min_mbps_down:
                socks5 = socks5.filter(Socks5.bandwidth >= min_mbps_down)
            if max_connect_time:
                socks5 = socks5.filter(Socks5.connect_time <= max_connect_time)

            result = socks5.order_by(
                Socks5.last_use.asc(), Socks5.last_check.desc()
            ).limit(limit).all()

            if result and update_usage:
                for s in result:
                    s.last_use = datetime.now()
                session.commit()

            if result:
                for s in result:
                    if update_usage:
                        session.refresh(s)
                    session.expunge(s)

        except SQLAlchemyError as e:
            log.error("Error finding socks5: %s",e)
        finally:
            session.close()

        return result

    def bulk_add_socks5(self, socks5_dict_list):
        """Bulk insert multiple socks5s
        @param socks5_dict_list: A list of dictionaries containing
        all filled in columns for each socks5 entry."""
        try:
            self.engine.execute(Socks5.__table__.insert(), socks5_dict_list)
            return True
        except SQLAlchemyError as e:
            log.error("Error bulk adding socks5 to database: %s", e)
            return False

    def set_operational(self, socks5_id, operational):
        """Change the operational status for the given socks5 to the
        given value False/True. The last_check value is automatically
        updated."""
        session = self.Session()
        try:
            socks5 = session.query(Socks5).get(socks5_id)
            if not socks5:
                return
            socks5.operational = operational
            socks5.last_check = datetime.now()
            session.commit()
        except SQLAlchemyError as e:
            log.error("Error updating operational status in database: %s", e)
        finally:
            session.close()

    def set_connect_time(self, socks5_id, connect_time):
        """Store the approx time it takes to connect to this socks5
        @param connect_time: float representing the connection time."""
        session = self.Session()
        try:
            session.query(Socks5).filter_by(
                id=socks5_id
            ).update({"connect_time": connect_time})
            session.commit()
        except SQLAlchemyError as e:
            log.error("Error updating connect time in database: %s", e)
        finally:
            session.close()

    def set_approx_bandwidth(self, socks5_id, bandwidth):
        """Store the approximate Mbit/s speed down
        @param bandwidth: float representing the mbit/s speed down."""
        session = self.Session()
        try:
            session.query(Socks5).filter_by(
                id=socks5_id
            ).update({"bandwidth": bandwidth})
            session.commit()
        except SQLAlchemyError as e:
            log.error("Error updating bandwidth in database: %s", e)
        finally:
            session.close()