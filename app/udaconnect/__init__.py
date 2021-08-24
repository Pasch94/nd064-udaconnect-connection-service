import os

from app.udaconnect.services import setup_grpc_server 

def start_grpc_server():
    SERVER_PORT_IPV4 = os.getenv('GRPC_PORT_CONNECTION', '7005')
    SERVER_PORT = ':'.join(['[::]', SERVER_PORT_IPV4])
    setup_grpc_server(SERVER_PORT)
    print("gRPC Server setup..")

