import os
import logging
import threading
import json
import grpc

from datetime import datetime, timedelta
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor

import app.udaconnect.proto.connection_pb2 as conn_pb2
import app.udaconnect.proto.connection_pb2_grpc as conn_pb2_grpc

from app.udaconnect.proto.person_pb2 import PersonListRequest
from app.udaconnect.proto.person_pb2_grpc import PersonServiceStub

from app import db, app
from app.udaconnect.models import Connection, Location, Person
from app.udaconnect.schemas import ConnectionSchema, LocationSchema, PersonSchema
from geoalchemy2.functions import ST_AsText, ST_Point
from sqlalchemy.sql import text

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("udaconnect-api")

GRPC_PORT = os.getenv('GRPC_PORT_PERSON', '6005')
GRPC_HOST = os.getenv('GRPC_HOST_PERSON', 'localhost')

DATE_FORMAT = "%Y-%m-%d"

print(':'.join([GRPC_HOST, GRPC_PORT]))
GRPC_CHANNEL = grpc.insecure_channel(':'.join([GRPC_HOST, GRPC_PORT]), options=(('grpc.enable_http_proxy', 0),))
grpc_stub = PersonServiceStub(GRPC_CHANNEL)

class ConnectionService:
    @staticmethod
    def find_contacts(person_id: int, start_date: datetime, end_date: datetime, meters=5
    ) -> List[Connection]:
        """
        Finds all Person who have been within a given distance of a given Person within a date range.

        This will run rather quickly locally, but this is an expensive method and will take a bit of time to run on
        large datasets. This is by design: what are some ways or techniques to help make this data integrate more
        smoothly for a better user experience for API consumers?
        """
        with app.app_context():
            locations: List = db.session.query(Location).filter(
                Location.person_id == person_id
            ).filter(Location.creation_time < end_date).filter(
                Location.creation_time >= start_date
            ).all()

            # Cache all users in memory for quick lookup
            person_map: Dict[str, Person] = {person.id: person for person in grpc_stub.GetAll(PersonListRequest()).persons}

            # Prepare arguments for queries
            data = []
            for location in locations:
                data.append(
                    {
                        "person_id": person_id,
                        "longitude": location.longitude,
                        "latitude": location.latitude,
                        "meters": int(meters),
                        "start_date": start_date.strftime("%Y-%m-%d"),
                        "end_date": (end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                    }
                )

        query = text(
            """
        SELECT  person_id, id, ST_X(coordinate), ST_Y(coordinate), creation_time
        FROM    location
        WHERE   ST_DWithin(coordinate::geography,ST_SetSRID(ST_MakePoint(:latitude,:longitude),4326)::geography, :meters)
        AND     person_id != :person_id
        AND     TO_DATE(:start_date, 'YYYY-MM-DD') <= creation_time
        AND     TO_DATE(:end_date, 'YYYY-MM-DD') > creation_time;
        """
        )
        result = []
        with app.app_context():
            for line in tuple(data):
                for (
                    exposed_person_id,
                    location_id,
                    exposed_lat,
                    exposed_long,
                    exposed_time,
                ) in db.engine.execute(query, **line):
                    location = conn_pb2.Location(
                        id=location_id,
                        person_id=exposed_person_id,
                        creation_time=datetime.timestamp(exposed_time),
                        longitude=exposed_long,
                        latitude=exposed_lat,
                    )

                    result.append(
                        conn_pb2.Connection(
                            person=person_map[exposed_person_id], location=location,
                        )
                    )

        return conn_pb2.ConnectionData(
                connections=result
                )

    # gRPC functions
    def Get(self, request, context):
        return self.find_contacts(
                person_id=request.person_id, 
                start_date=datetime.strptime(request.start_date, DATE_FORMAT), 
                end_date=datetime.strptime(request.end_date, DATE_FORMAT),
                meters=(request.meters or 5)
                )


def setup_grpc_server(server_port):
    server = grpc.server(ThreadPoolExecutor(max_workers=5))
    conn_pb2_grpc.add_ConnectionServiceServicer_to_server(ConnectionService(), server)
    server.add_insecure_port(server_port)

    def serve(server):
        server.start()
        logger.debug('gRPC server added')
        server.wait_for_termination()

    serve_thread = threading.Thread(target=serve, args=(server,))
    serve_thread.start()

